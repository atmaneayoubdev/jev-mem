"""Read-time pipeline: retrieve → expand → judge → policy → context.

Retrieval and intent judgment run concurrently. Candidate judgments run concurrently
under the judge client's own concurrency bound. If the judge fails, the pipeline falls
back to retriever order with lifecycle annotations and says so (`judge_used=False`);
it never fabricates a judgment.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from jevmem.judgment.base import CandidateJudgment, DecisionJudge, IntentJudgment
from jevmem.memory.context import (
    ContextBuilder,
    ContextEntry,
    ContextResult,
    TokenCounter,
    approx_tokens,
)
from jevmem.memory.lineage import Validity, conflict_partners, successors, validity_at
from jevmem.memory.models import LinkType, Memory
from jevmem.memory.store import MemoryStore
from jevmem.policy.engine import CandidateFacts, Decision, ReadDecision, ReadPolicy, ResolvedIntent
from jevmem.policy.thresholds import PolicyConfig
from jevmem.providers.errors import ProviderError
from jevmem.retrieval.base import CandidateRetriever, MemoryCandidate
from jevmem.retrieval.expansion import expand_candidates
from jevmem.timing import makespan


class RecallResult(BaseModel):
    query: str
    judge_used: bool
    fallback_reason: str | None = None
    intent: ResolvedIntent | None = None
    candidates: list[MemoryCandidate]
    facts: dict[str, CandidateFacts] = Field(default_factory=dict)
    judgments: dict[str, CandidateJudgment] = Field(default_factory=dict)
    intent_judgment: IntentJudgment | None = None
    decisions: list[ReadDecision] = Field(default_factory=list)
    context: ContextResult
    retrieval_ms: float = 0.0
    # Judge time on the query path, modelled from recorded per-call latencies (reproducible
    # under cache replay): intent overlaps retrieval, then candidate calls are scheduled
    # onto `judge_workers` concurrent slots.
    judge_ms: float = 0.0
    wall_ms: float = 0.0  # measured wall-clock of this recall (not reproducible under replay)
    judge_calls: int = 0
    judge_input_tokens: int = 0
    judge_cost: float | None = None

    @property
    def selected_ids(self) -> list[str]:
        return self.context.memory_ids


def candidate_facts(
    store: MemoryStore, memory: Memory, now: datetime, config: PolicyConfig
) -> CandidateFacts:
    ttl = config.write.ttl()
    uncertain = any(
        store.get(link.source_id).observed_at <= now
        for link in store.links_to(memory.id, [LinkType.UNCERTAIN_RELATION])
    )
    predecessor_of_current = any(
        validity_at(s, store, now, ttl) is Validity.CURRENT for s in successors(store, memory.id)
    )
    return CandidateFacts(
        memory_id=memory.id,
        validity=validity_at(memory, store, now, ttl),
        conflict_partner_ids=[p.id for p in conflict_partners(store, memory.id)],
        possibly_outdated=uncertain,
        immediate_predecessor_of_current=predecessor_of_current,
    )


def context_entries(
    candidates: Sequence[MemoryCandidate], decisions: Sequence[ReadDecision], config: PolicyConfig
) -> list[ContextEntry]:
    """Injected decisions → context entries, prioritised by utility (then relevance)."""
    memories = {c.memory.id: c.memory for c in candidates}
    entries = []
    for d in decisions:
        if not d.injected_under(config):
            continue
        entries.append(
            ContextEntry(
                memory=memories[d.memory_id],
                priority=(d.utility or 0.0) + 1e-3 * (d.relevance or 0.0),
                label=d.decision.value,
                annotations=d.annotations,
                conflict=d.decision is Decision.CONFLICT,
            )
        )
    return entries


def decide_and_build(
    candidates: Sequence[MemoryCandidate],
    judgments: Mapping[str, CandidateJudgment],
    intent: ResolvedIntent,
    store: MemoryStore,
    now: datetime,
    config: PolicyConfig,
    builder: ContextBuilder,
) -> tuple[dict[str, CandidateFacts], list[ReadDecision], ContextResult]:
    """The deterministic part of recall: facts → policy decisions → context. Pure given inputs,
    so the benchmark can replay it over cached judgments with any policy configuration."""
    policy = ReadPolicy(config)
    facts = {c.memory.id: candidate_facts(store, c.memory, now, config) for c in candidates}
    eligible = {
        c.memory.id: judgments[c.memory.id].relevance
        for c in candidates
        if policy.eligible(facts[c.memory.id], intent)
    }
    decisions = [
        policy.decide(judgments[c.memory.id], facts[c.memory.id], intent, eligible)
        for c in candidates
    ]
    context = builder.build(context_entries(candidates, decisions, config), now)
    return facts, decisions, context


class JudgedRecall:
    def __init__(
        self,
        store: MemoryStore,
        retriever: CandidateRetriever,
        judge: DecisionJudge,
        config: PolicyConfig,
        *,
        pool_size: int = 20,
        budget: int = 1024,
        expand: bool = True,
        fallback_k: int = 5,
        judge_workers: int = 16,
        counter: TokenCounter = approx_tokens,
    ) -> None:
        self.store = store
        self.retriever = retriever
        self.judge = judge
        self.config = config
        self.policy = ReadPolicy(config)
        self.pool_size = pool_size
        self.expand = expand
        self.fallback_k = fallback_k
        self.judge_workers = judge_workers
        self.builder = ContextBuilder(store, budget, counter)

    async def recall(self, query: str, user_id: str, now: datetime) -> RecallResult:
        t0 = time.perf_counter()
        retrieval_task = asyncio.create_task(
            self.retriever.retrieve(query, user_id, self.pool_size)
        )
        intent_task = asyncio.create_task(self.judge.intent(query))
        candidates = await retrieval_task
        retrieval_ms = (time.perf_counter() - t0) * 1000
        try:
            intent_judgment = await intent_task
        except ProviderError as exc:
            return self._fallback(
                query, candidates, now, retrieval_ms, f"intent judgment failed: {exc}"
            )
        intent = self.policy.resolve_intent(intent_judgment)
        if self.expand:
            candidates = expand_candidates(candidates, self.store, intent.intent)
        statuses = {
            c.memory.id: candidate_facts(self.store, c.memory, now, self.config).validity.value
            for c in candidates
        }
        try:
            judged = await asyncio.gather(
                *(
                    self.judge.candidate(query, c.memory.content, statuses[c.memory.id])
                    for c in candidates
                )
            )
        except ProviderError as exc:
            return self._fallback(
                query, candidates, now, retrieval_ms, f"candidate judgment failed: {exc}"
            )
        judge_ms = max(0.0, intent_judgment.meta.latency_ms - retrieval_ms) + makespan(
            [j.meta.latency_ms for j in judged], self.judge_workers
        )
        judgments = {c.memory.id: j for c, j in zip(candidates, judged, strict=True)}
        facts, decisions, context = decide_and_build(
            candidates, judgments, intent, self.store, now, self.config, self.builder
        )

        metas = [intent_judgment.meta, *(j.meta for j in judged)]
        costs = [m.cost for m in metas if m.cost is not None]
        return RecallResult(
            query=query,
            judge_used=True,
            intent=intent,
            intent_judgment=intent_judgment,
            candidates=candidates,
            facts=facts,
            judgments=judgments,
            decisions=decisions,
            context=context,
            retrieval_ms=retrieval_ms,
            judge_ms=judge_ms,
            wall_ms=(time.perf_counter() - t0) * 1000,
            judge_calls=len(metas),
            judge_input_tokens=sum(m.input_tokens or 0 for m in metas),
            judge_cost=sum(costs) if costs else None,
        )

    def _fallback(
        self,
        query: str,
        candidates: list[MemoryCandidate],
        now: datetime,
        retrieval_ms: float,
        reason: str,
    ) -> RecallResult:
        facts = {
            c.memory.id: candidate_facts(self.store, c.memory, now, self.config) for c in candidates
        }
        decisions = [
            self.policy.fallback(facts[c.memory.id], rank, self.fallback_k, reason)
            for rank, c in enumerate(candidates)
        ]
        memories = {c.memory.id: c.memory for c in candidates}
        entries = [
            ContextEntry(
                memory=memories[d.memory_id],
                priority=-float(rank),
                label=d.decision.value,
                annotations=d.annotations,
            )
            for rank, d in enumerate(decisions)
            if d.injected
        ]
        return RecallResult(
            query=query,
            judge_used=False,
            fallback_reason=reason,
            candidates=candidates,
            facts=facts,
            decisions=decisions,
            context=self.builder.build(entries, now),
            retrieval_ms=retrieval_ms,
        )
