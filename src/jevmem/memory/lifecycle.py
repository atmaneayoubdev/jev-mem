"""Write-time memory lifecycle.

For each new memory, in observation order:
1. find neighbours among *earlier* memories (active first, then a few superseded ones,
   so long version chains cannot crowd out current facts);
2. ask the judge for the memory's durability and for its relation to each neighbour;
3. let the deterministic WritePolicy turn those probabilities into links/status changes.

Nothing is ever deleted. If the judge fails, the memory is stored with
`lifecycle_pending=True` and no links, and can be re-judged later with the same
earlier-memories-only neighbour rule, so the outcome does not depend on when it runs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from jevmem.judgment.base import DecisionJudge, PairJudgment, ProfileJudgment
from jevmem.memory.lineage import expires_at, reinforce_cluster
from jevmem.memory.models import LinkType, Memory, MemoryLink, MemoryStatus
from jevmem.memory.store import MemoryStore
from jevmem.observability.logging import get_logger
from jevmem.policy.engine import WriteAction, WritePolicy
from jevmem.policy.thresholds import PolicyConfig
from jevmem.providers.errors import ProviderError
from jevmem.retrieval.base import MemoryIndex

log = get_logger("lifecycle")


class PairOutcome(BaseModel):
    earlier_id: str
    relation: str
    probabilities: dict[str, float]
    action: WriteAction


class WriteReport(BaseModel):
    memory_id: str
    neighbor_ids: list[str] = Field(default_factory=list)
    durability: str | None = None
    pairs: list[PairOutcome] = Field(default_factory=list)
    propagated_ids: list[str] = Field(default_factory=list)
    pending: bool = False
    error: str | None = None
    judge_calls: int = 0
    judge_latency_ms: float = 0.0  # wall-clock for this memory's (concurrent) judgments


class LifecyclePipeline:
    def __init__(
        self,
        store: MemoryStore,
        index: MemoryIndex,
        judge: DecisionJudge | None,
        config: PolicyConfig,
        *,
        active_neighbors: int = 5,
        superseded_neighbors: int = 2,
        min_embedding_similarity: float = 0.45,
        rrf_k: int = 60,
    ) -> None:
        self.store = store
        self.index = index
        self.judge = judge
        self.config = config
        self.policy = WritePolicy(config)
        self.active_neighbors = active_neighbors
        self.superseded_neighbors = superseded_neighbors
        # Dense search always returns *something*; without a floor every memory would be
        # paired with unrelated ones (wasted judge calls, and case-specific pairs that defeat
        # caching). The floor's effect on real relations is measured as neighbour recall.
        self.min_embedding_similarity = min_embedding_similarity
        self.rrf_k = rrf_k
        self._last_key: dict[str, tuple[object, ...]] = {}

    async def write_many(self, memories: Sequence[Memory]) -> list[WriteReport]:
        """Write in observation order. Each write can depend on earlier lifecycle decisions."""
        return [await self.write(m) for m in sorted(memories, key=lambda m: m.order_key)]

    async def write(self, memory: Memory) -> WriteReport:
        last = self._last_key.get(memory.user_id)
        if last is not None and memory.order_key < last:
            raise ValueError(
                f"memory {memory.id} is older than the last write; writes must follow observed_at "
                "order (use write_many for backfills)"
            )
        self._last_key[memory.user_id] = memory.order_key
        neighbors = self.neighbors(memory)
        self.store.add(memory)
        self.index.add(memory)
        if self.judge is None:
            return WriteReport(memory_id=memory.id)
        return await self._judge_and_apply(memory, neighbors)

    async def rejudge_pending(self, user_id: str) -> list[WriteReport]:
        pending = [m for m in self.store.list_memories(user_id) if m.lifecycle_pending]
        return [await self._judge_and_apply(m, self.neighbors(m)) for m in pending]

    def neighbors(self, memory: Memory) -> list[Memory]:
        """Nearest earlier memories: top active ones, then a few superseded ones."""
        user = self.index.user(memory.user_id)
        position = {mid: i for i, mid in enumerate(user.order)}
        limit_pos = position.get(memory.id, len(user.order))
        fused: dict[str, float] = {}
        rankings = [user.bm25.search(memory.content)]
        if user.embedding is not None:
            rankings.append(
                [
                    r
                    for r in user.embedding.search_similar(memory.content)
                    if r.score >= self.min_embedding_similarity
                ]
            )
        for ranking in rankings:
            for rank, item in enumerate(
                r for r in ranking if position.get(r.memory_id, limit_pos) < limit_pos
            ):
                fused[item.memory_id] = fused.get(item.memory_id, 0.0) + 1.0 / (
                    self.rrf_k + rank + 1
                )
        active: list[Memory] = []
        superseded: list[Memory] = []
        for mid in sorted(fused, key=lambda i: (-fused[i], i)):
            if (
                len(active) >= self.active_neighbors
                and len(superseded) >= self.superseded_neighbors
            ):
                break
            candidate = self.store.get(mid)
            if candidate.status is MemoryStatus.ACTIVE and len(active) < self.active_neighbors:
                active.append(candidate)
            elif (
                candidate.status is MemoryStatus.SUPERSEDED
                and len(superseded) < self.superseded_neighbors
            ):
                superseded.append(candidate)
        return active + superseded

    async def _judge_and_apply(self, memory: Memory, neighbors: list[Memory]) -> WriteReport:
        assert self.judge is not None
        report = WriteReport(memory_id=memory.id, neighbor_ids=[n.id for n in neighbors])
        start = time.perf_counter()
        try:
            profile, pairs = await asyncio.gather(
                self.judge.profile(memory.content),
                asyncio.gather(*(self.judge.pair(n.content, memory.content) for n in neighbors)),
            )
        except ProviderError as exc:
            stored = self.store.get(memory.id)
            stored.lifecycle_pending = True
            self.store.update(stored)
            log.warning(
                "lifecycle judgment failed",
                extra={"memory_id": memory.id, "error": type(exc).__name__},
            )
            report.pending = True
            report.error = str(exc)
            return report
        report.judge_calls = 1 + len(neighbors)
        report.judge_latency_ms = (time.perf_counter() - start) * 1000
        self._apply(memory.id, profile, list(zip(neighbors, pairs, strict=True)), report)
        return report

    def _apply(
        self,
        memory_id: str,
        profile: ProfileJudgment,
        pairs: list[tuple[Memory, PairJudgment]],
        report: WriteReport,
    ) -> None:
        memory = self.store.get(memory_id)
        decision = self.policy.profile(profile)
        memory.durability = decision.durability
        memory.horizon = decision.horizon
        memory.lifecycle_pending = False
        self.store.update(memory)
        report.durability = decision.durability.value
        judge_id = f"{profile.meta.judge}:{profile.meta.model}"

        for earlier, judgment in pairs:
            action = self.policy.pair(judgment, memory.durability)
            report.pairs.append(
                PairOutcome(
                    earlier_id=earlier.id,
                    relation=judgment.relation.choice,
                    probabilities=judgment.relation.probabilities,
                    action=action,
                )
            )
            if action.link_type is None:
                continue
            expiry = (
                expires_at(memory, self.config.write.ttl())
                if action.link_type is LinkType.TEMPORARILY_OVERRIDES
                else None
            )
            self._link(action.link_type, memory, earlier.id, judgment, judge_id, expiry)
            if action.supersede_earlier:
                report.propagated_ids += self._supersede(memory, earlier.id, judgment, judge_id)

    def _supersede(
        self, later: Memory, earlier_id: str, judgment: PairJudgment, judge_id: str
    ) -> list[str]:
        """Mark `earlier_id` and its earlier REINFORCES-cluster members superseded."""
        propagated: list[str] = []
        for member in reinforce_cluster(self.store, earlier_id):
            if member.id == later.id or member.order_key >= later.order_key:
                continue
            if member.status is not MemoryStatus.ACTIVE:
                continue
            member.status = MemoryStatus.SUPERSEDED
            self.store.update(member)
            if member.id != earlier_id:
                self._link(LinkType.SUPERSEDES, later, member.id, judgment, judge_id, None)
                propagated.append(member.id)
        return propagated

    def _link(
        self,
        link_type: LinkType,
        source: Memory,
        target_id: str,
        judgment: PairJudgment,
        judge_id: str,
        expiry: datetime | None,
    ) -> None:
        self.store.add_link(
            MemoryLink(
                link_type=link_type,
                source_id=source.id,
                target_id=target_id,
                probabilities=judgment.relation.probabilities,
                confidence=judgment.relation.confidence,
                judge=judge_id,
                question_schema_version=judgment.meta.schema_version,
                policy_version=self.config.version,
                expires_at=expiry,
            )
        )
