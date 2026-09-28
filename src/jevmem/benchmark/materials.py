"""Per-case materials: the one expensive pass ("judge once, decide many").

For each case this builds, once:
- a plain store (no lifecycle) and full rankings from every retriever;
- for each judge (Jev, Qwen), a store whose write-time lifecycle was run by that judge,
  the query-intent judgment, and candidate judgments for the *union* of every candidate
  pool any system can draw (all first-stage retrievers up to `pool_max`, plus every
  link expansion under any intent).

Every system, threshold setting, and ablation is then computed offline from these
materials (`systems.py`) without further model calls.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from jevmem.benchmark.datasets.background import BackgroundMemory, with_background
from jevmem.benchmark.datasets.schema import Case
from jevmem.judgment.base import CandidateJudgment, DecisionJudge, IntentJudgment
from jevmem.memory.lifecycle import LifecyclePipeline, WriteReport
from jevmem.memory.models import Durability, Memory
from jevmem.memory.recall import candidate_facts
from jevmem.memory.store import InMemoryStore
from jevmem.policy.thresholds import PolicyConfig
from jevmem.providers.errors import ProviderError
from jevmem.retrieval.base import MemoryCandidate, MemoryIndex
from jevmem.retrieval.bm25 import ScoredId
from jevmem.retrieval.embedding import Embedder
from jevmem.retrieval.expansion import expand_candidates
from jevmem.retrieval.rerank import CrossEncoderScorer

RERANK_POOL = 50


@dataclass
class Resources:
    judges: Mapping[str, DecisionJudge]  # e.g. {"jev": JevJudge, "qwen": QwenJudge}
    embedder: Embedder | None
    reranker: CrossEncoderScorer | None
    background: Sequence[BackgroundMemory]
    write_policy: PolicyConfig
    min_embedding_similarity: float = 0.40
    readonly_judges: Sequence[str] = ()


@dataclass
class JudgedStore:
    judge: str
    store: InMemoryStore
    index: MemoryIndex
    reports: list[WriteReport]
    intent: IntentJudgment | None = None
    candidates: dict[str, CandidateJudgment] = field(default_factory=dict)
    failure: str | None = None  # set when the judge failed; the case is flagged, never faked

    @property
    def pending_writes(self) -> int:
        return sum(r.pending for r in self.reports)


@dataclass
class CaseMaterials:
    case: Case
    memories: list[Memory]
    store: InMemoryStore
    index: MemoryIndex
    rankings: dict[str, list[ScoredId]]
    retrieval_ms: dict[str, float]
    judged: dict[str, JudgedStore]
    n_background: int


def to_memories(
    case: Case, background: Sequence[BackgroundMemory], n_background: int
) -> list[Memory]:
    return [
        Memory(
            id=m.id,
            user_id=case.user_id,
            content=m.content,
            observed_at=m.observed_at,
            created_at=m.observed_at,
            sequence=m.sequence,
        )
        for m in with_background(case, background, n_background)
    ]


def _fresh(memories: Sequence[Memory]) -> list[Memory]:
    return [m.model_copy(deep=True) for m in memories]


def _rankings(
    case: Case, index: MemoryIndex, res: Resources
) -> tuple[dict[str, list[ScoredId]], dict[str, float]]:
    user = index.user(case.user_id)
    rankings: dict[str, list[ScoredId]] = {}
    timing: dict[str, float] = {}

    t = time.perf_counter()
    rankings["bm25"] = user.bm25.search(case.query)
    timing["bm25"] = (time.perf_counter() - t) * 1000

    order = user.order
    rankings["recency"] = [
        ScoredId(mid, float(len(order) - i)) for i, mid in enumerate(reversed(order))
    ]
    timing["recency"] = 0.0

    if user.embedding is not None:
        t = time.perf_counter()
        rankings["embedding"] = user.embedding.search(case.query)
        timing["embedding"] = (time.perf_counter() - t) * 1000
        if res.reranker is not None:
            pool = rankings["embedding"][:RERANK_POOL]
            texts = [index.store.get(s.memory_id).content for s in pool]
            t = time.perf_counter()
            scores = res.reranker.score(case.query, texts)
            timing["rerank"] = timing["embedding"] + (time.perf_counter() - t) * 1000
            ranked = sorted(
                zip(pool, scores, strict=True), key=lambda ps: (-ps[1], ps[0].memory_id)
            )
            rankings["rerank"] = [ScoredId(p.memory_id, s) for p, s in ranked]
    return rankings, timing


def candidate_union(rankings: Mapping[str, Sequence[ScoredId]], pool_max: int) -> list[str]:
    seen: dict[str, None] = {}
    for name in ("bm25", "embedding", "recency"):
        for item in rankings.get(name, [])[:pool_max]:
            seen.setdefault(item.memory_id, None)
    return list(seen)


async def _judge_store(
    name: str,
    judge: DecisionJudge,
    case: Case,
    memories: Sequence[Memory],
    rankings: Mapping[str, Sequence[ScoredId]],
    res: Resources,
    pool_max: int,
) -> JudgedStore:
    store = InMemoryStore()
    index = MemoryIndex(store, res.embedder)
    pipeline = LifecyclePipeline(
        store, index, judge, res.write_policy, min_embedding_similarity=res.min_embedding_similarity
    )
    reports = await pipeline.write_many(_fresh(memories))
    judged = JudgedStore(judge=name, store=store, index=index, reports=reports)
    if judged.pending_writes:
        judged.failure = f"{judged.pending_writes} lifecycle writes pending"
    await _read_judgments(judged, judge, case, rankings, res, pool_max)
    return judged


async def _read_judgments(
    judged: JudgedStore,
    judge: DecisionJudge,
    case: Case,
    rankings: Mapping[str, Sequence[ScoredId]],
    res: Resources,
    pool_max: int,
) -> None:
    """Intent + candidate judgments for the union of every pool any system can draw."""
    store = judged.store
    try:
        judged.intent = await judge.intent(case.query)
        base = [
            MemoryCandidate(memory=store.get(mid), score=0.0, rank=i)
            for i, mid in enumerate(candidate_union(rankings, pool_max))
        ]
        # superset of every expansion any system can perform (predecessors need "both")
        expanded = expand_candidates(base, store, "both", max_added=len(base) + 50)
        statuses = [
            candidate_facts(store, c.memory, case.now, res.write_policy).validity.value
            for c in expanded
        ]
        results = await asyncio.gather(
            *(
                judge.candidate(case.query, c.memory.content, status)
                for c, status in zip(expanded, statuses, strict=True)
            )
        )
        judged.candidates = {c.memory.id: j for c, j in zip(expanded, results, strict=True)}
    except ProviderError as exc:
        judged.failure = f"read-time judgment failed: {exc}"


async def materialize(
    case: Case, res: Resources, *, n_background: int, pool_max: int
) -> CaseMaterials:
    memories = to_memories(case, res.background, n_background)
    store = InMemoryStore()
    index = MemoryIndex(store, res.embedder)
    await LifecyclePipeline(store, index, None, res.write_policy).write_many(_fresh(memories))
    rankings, timing = _rankings(case, index, res)
    judged_list = list(
        await asyncio.gather(
            *(
                _judge_store(name, judge, case, memories, rankings, res, pool_max)
                for name, judge in res.judges.items()
            )
        )
    )
    for name in res.readonly_judges:
        # Ablation: read-time judgments on the plain store (no lifecycle links, all current).
        readonly = JudgedStore(judge=f"{name}-readonly", store=store, index=index, reports=[])
        await _read_judgments(readonly, res.judges[name], case, rankings, res, pool_max)
        judged_list.append(readonly)
    return CaseMaterials(
        case=case,
        memories=memories,
        store=store,
        index=index,
        rankings=rankings,
        retrieval_ms=timing,
        judged={j.judge: j for j in judged_list},
        n_background=n_background,
    )


def durability_of(judged: JudgedStore, memory_id: str) -> Durability | None:
    return judged.store.get(memory_id).durability
