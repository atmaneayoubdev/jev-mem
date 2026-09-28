"""Benchmark systems, computed offline from `CaseMaterials`.

Every system renders its selection through the same `ContextBuilder` with the same
budget. Tunable parameters (K, thresholds, half-life, policy thresholds) come from a
calibration file produced on the calib split only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from jevmem.benchmark.materials import CaseMaterials, JudgedStore
from jevmem.memory.context import ContextBuilder, ContextEntry, ContextResult
from jevmem.memory.recall import decide_and_build
from jevmem.policy.engine import Decision, ReadPolicy
from jevmem.policy.thresholds import PolicyConfig
from jevmem.retrieval.base import MemoryCandidate
from jevmem.retrieval.bm25 import ScoredId
from jevmem.retrieval.expansion import expand_candidates
from jevmem.timing import makespan

Kind = Literal["topk", "threshold", "decay", "heuristic_lifecycle", "judged"]


class SystemSpec(BaseModel):
    name: str
    kind: Kind
    ranking: str | None = None  # recency | bm25 | embedding | rerank (baselines)
    judge: str | None = None  # jev | qwen (judged systems)
    first_stage: str | None = None  # bm25 | embedding | hybrid (judged systems)
    needs_embeddings: bool = False
    description: str = ""


SYSTEMS: dict[str, SystemSpec] = {
    s.name: s
    for s in [
        SystemSpec(
            name="recency", kind="topk", ranking="recency", description="Most recent K memories"
        ),
        SystemSpec(name="bm25", kind="topk", ranking="bm25", description="BM25 top-K"),
        SystemSpec(
            name="embedding",
            kind="topk",
            ranking="embedding",
            needs_embeddings=True,
            description="Dense top-K",
        ),
        SystemSpec(
            name="embedding-threshold",
            kind="threshold",
            ranking="embedding",
            needs_embeddings=True,
            description="Dense, cosine >= calibrated threshold",
        ),
        SystemSpec(
            name="embedding-decay",
            kind="decay",
            ranking="embedding",
            needs_embeddings=True,
            description="Dense score x recency decay, top-K",
        ),
        SystemSpec(
            name="embedding-lifecycle",
            kind="heuristic_lifecycle",
            ranking="embedding",
            needs_embeddings=True,
            description="Dense top-K, newest wins within near-duplicate clusters",
        ),
        SystemSpec(
            name="rerank",
            kind="topk",
            ranking="rerank",
            needs_embeddings=True,
            description="Dense top-50 -> cross-encoder, top-K",
        ),
        SystemSpec(
            name="rerank-threshold",
            kind="threshold",
            ranking="rerank",
            needs_embeddings=True,
            description="Cross-encoder score >= calibrated threshold",
        ),
        SystemSpec(
            name="bm25-jev",
            kind="judged",
            judge="jev",
            first_stage="bm25",
            description="BM25 -> Jev -> policy",
        ),
        SystemSpec(
            name="embedding-jev",
            kind="judged",
            judge="jev",
            first_stage="embedding",
            needs_embeddings=True,
            description="Dense -> Jev -> policy",
        ),
        SystemSpec(
            name="hybrid-jev",
            kind="judged",
            judge="jev",
            first_stage="hybrid",
            needs_embeddings=True,
            description="BM25+dense+recency -> Jev -> policy",
        ),
        SystemSpec(
            name="hybrid-qwen",
            kind="judged",
            judge="qwen",
            first_stage="hybrid",
            needs_embeddings=True,
            description="BM25+dense+recency -> Qwen-as-judge -> policy",
        ),
    ]
}


class Params(BaseModel):
    """Calibrated parameters for every system (defaults are pre-calibration)."""

    k: dict[str, int] = Field(
        default_factory=lambda: {
            "recency": 5,
            "bm25": 5,
            "embedding": 5,
            "rerank": 5,
            "embedding-decay": 5,
            "embedding-lifecycle": 5,
        }
    )
    threshold: dict[str, float] = Field(
        default_factory=lambda: {"embedding-threshold": 0.5, "rerank-threshold": 0.5}
    )
    half_life_days: float = 180.0
    duplicate_similarity: float = 0.8
    pool_size: int = 20
    judge_workers: int = 16
    policy: dict[str, PolicyConfig] = Field(
        default_factory=lambda: {"jev": PolicyConfig(), "qwen": PolicyConfig()}
    )


class Selection(BaseModel):
    system: str
    selected_ids: list[str]
    ranked_ids: list[str]
    candidate_ids: list[str] = Field(default_factory=list)  # first-stage pool
    expanded_ids: list[str] = Field(default_factory=list)  # after link expansion
    decisions: dict[str, str] = Field(default_factory=dict)
    intent: str | None = None
    intent_low_confidence: bool = False
    context_text: str
    context_tokens: int
    judge_used: bool = False
    failure: str | None = None
    retrieval_ms: float = 0.0
    judge_ms: float = 0.0
    judge_calls: int = 0
    judge_input_tokens: int = 0
    judge_cost: float | None = None


def _rrf(rankings: Sequence[Sequence[ScoredId]], limit: int, k: int = 60) -> list[str]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking[:limit]):
            fused[item.memory_id] = fused.get(item.memory_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused, key=lambda mid: (-fused[mid], mid))[:limit]


def _baseline_context(mat: CaseMaterials, ids: Sequence[str], budget: int) -> ContextResult:
    entries = [
        ContextEntry(memory=mat.store.get(mid), priority=-float(rank), label="rank")
        for rank, mid in enumerate(ids)
    ]
    return ContextBuilder(mat.store, budget).build(entries, mat.case.now)


def _baseline(
    spec: SystemSpec, mat: CaseMaterials, params: Params, budget: int, k_override: int | None
) -> Selection:
    assert spec.ranking is not None
    ranking = mat.rankings.get(spec.ranking, [])
    now = mat.case.now
    match spec.kind:
        case "topk":
            ids = [s.memory_id for s in ranking[: k_override or params.k[spec.name]]]
        case "threshold":
            ids = [s.memory_id for s in ranking if s.score >= params.threshold[spec.name]]
        case "decay":

            def decayed(s: ScoredId) -> float:
                age = max(
                    0.0, (now - mat.store.get(s.memory_id).observed_at).total_seconds() / 86400
                )
                return float(s.score * 0.5 ** (age / params.half_life_days))

            ranking = sorted(ranking, key=lambda s: (-decayed(s), s.memory_id))
            ids = [s.memory_id for s in ranking[: params.k[spec.name]]]
        case "heuristic_lifecycle":
            ids = _newest_per_cluster(mat, ranking[: params.pool_size], params.duplicate_similarity)
            ids = ids[: params.k[spec.name]]
        case _:
            raise ValueError(spec.kind)
    context = _baseline_context(mat, ids, budget)
    return Selection(
        system=spec.name,
        selected_ids=context.memory_ids,
        ranked_ids=[s.memory_id for s in ranking],
        context_text=context.text,
        context_tokens=context.tokens,
        retrieval_ms=mat.retrieval_ms.get(spec.ranking, 0.0),
    )


def _newest_per_cluster(
    mat: CaseMaterials, pool: Sequence[ScoredId], threshold: float
) -> list[str]:
    """Group near-duplicates (cosine > threshold) and keep only the newest of each group."""
    emb = mat.index.user(mat.case.user_id).embedding
    assert emb is not None
    ids = [s.memory_id for s in pool]
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if emb.similarity(a, b) > threshold:
                parent[find(a)] = find(b)
    newest: dict[str, str] = {}
    for mid in ids:
        root = find(mid)
        if (
            root not in newest
            or mat.store.get(mid).order_key > mat.store.get(newest[root]).order_key
        ):
            newest[root] = mid
    keep = set(newest.values())
    return [mid for mid in ids if mid in keep]


def _first_stage(spec: SystemSpec, mat: CaseMaterials, pool: int) -> list[str]:
    r = mat.rankings
    match spec.first_stage:
        case "bm25":
            return [s.memory_id for s in r["bm25"][:pool]]
        case "embedding":
            return [s.memory_id for s in r["embedding"][:pool]]
        case "hybrid":
            sources = [r["bm25"], r["recency"]] + ([r["embedding"]] if "embedding" in r else [])
            return _rrf(sources, pool)
        case _:
            raise ValueError(spec.first_stage)


def _first_stage_ms(spec: SystemSpec, mat: CaseMaterials) -> float:
    t = mat.retrieval_ms
    if spec.first_stage == "hybrid":
        return max(t.get("bm25", 0.0), t.get("embedding", 0.0))
    return t.get(spec.first_stage or "", 0.0)


def _judged(
    spec: SystemSpec,
    mat: CaseMaterials,
    params: Params,
    budget: int,
    policy: PolicyConfig | None,
    pool: int | None,
) -> Selection:
    assert spec.judge is not None
    judged: JudgedStore = mat.judged[spec.judge]
    config = policy or params.policy[spec.judge]
    pool_size = pool or params.pool_size
    first = _first_stage(spec, mat, pool_size)
    retrieval_ms = _first_stage_ms(spec, mat)
    if judged.failure is not None or judged.intent is None:
        return Selection(
            system=spec.name,
            selected_ids=[],
            ranked_ids=[],
            candidate_ids=first,
            context_text="",
            context_tokens=0,
            failure=judged.failure or "no intent judgment",
            retrieval_ms=retrieval_ms,
        )
    intent = ReadPolicy(config).resolve_intent(judged.intent)
    base = [
        MemoryCandidate(memory=judged.store.get(mid), score=0.0, rank=i)
        for i, mid in enumerate(first)
    ]
    candidates = expand_candidates(base, judged.store, intent.intent)
    missing = [c.memory.id for c in candidates if c.memory.id not in judged.candidates]
    if missing:
        raise RuntimeError(
            f"{mat.case.case_id}/{spec.name}: unjudged candidates {missing[:3]} (pool > pool_max?)"
        )
    judgments = {c.memory.id: judged.candidates[c.memory.id] for c in candidates}
    builder = ContextBuilder(judged.store, budget)
    _facts, decisions, context = decide_and_build(
        candidates, judgments, intent, judged.store, mat.case.now, config, builder
    )

    by_id = {d.memory_id: d for d in decisions}
    rejected = {Decision.STALE, Decision.DROP}
    ranked = sorted(
        by_id,
        key=lambda mid: (
            by_id[mid].decision in rejected,
            -(by_id[mid].utility or 0.0),
            -(by_id[mid].relevance or 0.0),
            mid,
        ),
    )
    metas = [judged.intent.meta, *(j.meta for j in judgments.values())]
    costs = [m.cost for m in metas if m.cost is not None]
    judge_ms = max(0.0, judged.intent.meta.latency_ms - retrieval_ms) + makespan(
        [j.meta.latency_ms for j in judgments.values()], params.judge_workers
    )
    return Selection(
        system=spec.name,
        selected_ids=context.memory_ids,
        ranked_ids=ranked,
        candidate_ids=first,
        expanded_ids=[c.memory.id for c in candidates],
        decisions={d.memory_id: d.decision.value for d in decisions},
        intent=intent.intent,
        intent_low_confidence=intent.low_confidence,
        context_text=context.text,
        context_tokens=context.tokens,
        judge_used=True,
        retrieval_ms=retrieval_ms,
        judge_ms=judge_ms,
        judge_calls=len(metas),
        judge_input_tokens=sum(m.input_tokens or 0 for m in metas),
        judge_cost=sum(costs) if costs else None,
    )


def select(
    spec: SystemSpec,
    mat: CaseMaterials,
    params: Params,
    budget: int,
    *,
    policy: PolicyConfig | None = None,
    pool: int | None = None,
    k_override: int | None = None,
) -> Selection:
    if spec.kind == "judged":
        return _judged(spec, mat, params, budget, policy, pool)
    return _baseline(spec, mat, params, budget, k_override)


def available(names: Sequence[str], materials: CaseMaterials) -> list[SystemSpec]:
    specs = []
    for name in names:
        spec = SYSTEMS[name]
        if spec.needs_embeddings and "embedding" not in materials.rankings:
            continue
        if spec.ranking == "rerank" and "rerank" not in materials.rankings:
            continue
        if spec.judge is not None and spec.judge not in materials.judged:
            continue
        specs.append(spec)
    return specs


def params_summary(params: Params) -> Mapping[str, Any]:
    return params.model_dump(mode="json")
