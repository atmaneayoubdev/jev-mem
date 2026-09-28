"""Per-case metrics (retrieval, answer, lifecycle) and their aggregation."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from jevmem.benchmark.answer import AnswerResult
from jevmem.benchmark.datasets.schema import Case
from jevmem.benchmark.materials import JudgedStore
from jevmem.benchmark.scoring import AnswerScore, score_answer
from jevmem.benchmark.stats import Estimate, cluster_bootstrap
from jevmem.benchmark.systems import Selection
from jevmem.memory.models import LinkType

K_VALUES = (1, 3, 5, 10)


class CaseResult(BaseModel):
    case_id: str
    split: str
    category: str
    family: str
    system: str
    selection: Selection
    answer: AnswerResult | None = None
    score: AnswerScore | None = None
    failed: bool = False
    # selection metrics
    selection_correct: bool
    required_recall: float | None
    forbidden_selected: bool
    neutral_selected: int
    background_selected: int
    # ranking metrics (None when there is no required memory or no ranking)
    recall_at: dict[int, float | None] = Field(default_factory=dict)
    mrr: float | None = None
    ndcg10: float | None = None
    # judged systems
    first_stage_recall: bool | None = None
    expanded_recall: bool | None = None
    intent_correct: bool | None = None
    end_to_end_ms: float | None = None


def _ndcg(ranked: Sequence[str], relevant: set[str], k: int = 10) -> float | None:
    if not relevant:
        return None
    dcg = sum(1.0 / math.log2(i + 2) for i, mid in enumerate(ranked[:k]) if mid in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal


def case_result(
    case: Case,
    selection: Selection,
    answer: AnswerResult | None,
    score: AnswerScore | None = None,
) -> CaseResult:
    required = case.ids_with("required")
    forbidden = case.ids_with("forbidden")
    neutral = case.ids_with("neutral")
    selected = set(selection.selected_ids)
    ranked = selection.ranked_ids
    failed = selection.failure is not None
    first_hit = next((i for i, mid in enumerate(ranked) if mid in required), None)
    if score is None and answer is not None and case.expected.mode != "llm_judge":
        score = score_answer(answer.answer, case.expected)
    judged = selection.judge_used
    return CaseResult(
        case_id=case.case_id,
        split=case.split,
        category=case.category,
        family=case.family,
        system=selection.system,
        selection=selection,
        answer=answer,
        score=score,
        failed=failed,
        selection_correct=not failed and required <= selected and not (selected & forbidden),
        required_recall=(len(required & selected) / len(required)) if required else None,
        forbidden_selected=bool(selected & forbidden),
        neutral_selected=len(selected & neutral)
        + sum(1 for mid in selected if mid.startswith("bg")),
        background_selected=sum(1 for mid in selected if mid.startswith("bg")),
        recall_at={
            k: (len(required & set(ranked[:k])) / len(required)) if required else None
            for k in K_VALUES
        },
        mrr=(1.0 / (first_hit + 1) if first_hit is not None else 0.0) if required else None,
        ndcg10=_ndcg(ranked, required),
        first_stage_recall=(required <= set(selection.candidate_ids))
        if judged and required
        else None,
        expanded_recall=(required <= set(selection.expanded_ids)) if judged and required else None,
        intent_correct=(selection.intent == case.intent) if judged else None,
        end_to_end_ms=(
            max(selection.retrieval_ms, 0.0) + selection.judge_ms + answer.latency_ms
            if answer is not None
            else None
        ),
    )


# --- lifecycle ------------------------------------------------------------------------

_LINK_TO_RELATION = {
    LinkType.SUPERSEDES: "supersedes",
    LinkType.TEMPORARILY_OVERRIDES: "supersedes",
    LinkType.CONFLICTS_WITH: "contradicts",
    LinkType.REINFORCES: "duplicate",
    LinkType.REFINES: "refines",
    LinkType.UNCERTAIN_RELATION: "uncertain",
}


class RelationOutcome(BaseModel):
    case_id: str
    family: str
    category: str
    judge: str
    earlier: str
    later: str
    gold: str
    predicted: str  # a relation, "uncertain", or "not_paired" (never compared)
    paired: bool
    # the judge's distribution for this pair (None when never compared)
    probabilities: dict[str, float] | None = None
    judged_choice: str | None = None


class DurabilityOutcome(BaseModel):
    case_id: str
    family: str
    judge: str
    memory_id: str
    gold: str
    predicted: str | None


def lifecycle_outcomes(
    case: Case, judged: JudgedStore
) -> tuple[list[RelationOutcome], list[DurabilityOutcome]]:
    reports = {r.memory_id: r for r in judged.reports}
    relations = []
    for rel in case.relations:
        links = [
            link for link in judged.store.links_from(rel.later) if link.target_id == rel.earlier
        ]
        paired = rel.earlier in reports[rel.later].neighbor_ids if rel.later in reports else False
        if links:
            predicted = _LINK_TO_RELATION[links[0].link_type]
        else:
            predicted = "unrelated" if paired else "not_paired"
        outcome = (
            next((p for p in reports[rel.later].pairs if p.earlier_id == rel.earlier), None)
            if rel.later in reports
            else None
        )
        relations.append(
            RelationOutcome(
                probabilities=outcome.probabilities if outcome else None,
                judged_choice=outcome.relation if outcome else None,
                case_id=case.case_id,
                family=case.family,
                category=case.category,
                judge=judged.judge,
                earlier=rel.earlier,
                later=rel.later,
                gold=rel.relation,
                predicted=predicted,
                paired=paired,
            )
        )
    durability = [
        DurabilityOutcome(
            case_id=case.case_id,
            family=case.family,
            judge=judged.judge,
            memory_id=m.id,
            gold=m.durability,
            predicted=(d.value if (d := judged.store.get(m.id).durability) is not None else None),
        )
        for m in case.memories
        if m.durability is not None
    ]
    return relations, durability


# --- aggregation ----------------------------------------------------------------------


def _by_family(results: Iterable[CaseResult], value: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in results:
        v = _value(r, value)
        if v is not None:
            out[r.family].append(v)
    return out


def _value(r: CaseResult, name: str) -> float | None:
    match name:
        case "answer_correct":
            return None if r.score is None else float(r.score.correct)
        case "forbidden_in_answer":
            return None if r.score is None else float(r.score.forbidden_used)
        case "context_tokens":
            return float(r.selection.context_tokens)
        case "judge_ms" | "retrieval_ms":
            return float(getattr(r.selection, name))
        case "judge_cost":
            return r.selection.judge_cost
        case _:
            if name.startswith("recall@"):
                return r.recall_at.get(int(name.split("@")[1]))
            v = getattr(r, name)
            return None if v is None else float(v)


METRICS = [
    "answer_correct",
    "selection_correct",
    "required_recall",
    "forbidden_selected",
    "forbidden_in_answer",
    "neutral_selected",
    "background_selected",
    "recall@1",
    "recall@5",
    "mrr",
    "ndcg10",
    "first_stage_recall",
    "expanded_recall",
    "intent_correct",
    "context_tokens",
    "retrieval_ms",
    "judge_ms",
    "end_to_end_ms",
    "judge_cost",
]


def aggregate(
    results: Sequence[CaseResult], *, n_boot: int = 2000
) -> dict[str, dict[str, Estimate]]:
    """{system: {metric: estimate}}; failed judged cases are excluded and counted separately."""
    out: dict[str, dict[str, Estimate]] = {}
    systems = sorted({r.system for r in results})
    for system in systems:
        rows = [r for r in results if r.system == system and not r.failed]
        out[system] = {m: cluster_bootstrap(_by_family(rows, m), n_boot=n_boot) for m in METRICS}
        failed = sum(1 for r in results if r.system == system and r.failed)
        out[system]["failed_cases"] = Estimate(
            mean=float(failed), lo=float(failed), hi=float(failed), n=failed
        )
    return out


def aggregate_by_category(
    results: Sequence[CaseResult],
    metrics: Sequence[str] = ("answer_correct", "selection_correct", "forbidden_selected"),
) -> dict[str, dict[str, dict[str, Estimate]]]:
    out: dict[str, dict[str, dict[str, Estimate]]] = defaultdict(dict)
    for category in sorted({r.category for r in results}):
        for system in sorted({r.system for r in results}):
            rows = [
                r for r in results if r.system == system and r.category == category and not r.failed
            ]
            out[category][system] = {
                m: cluster_bootstrap(_by_family(rows, m), n_boot=500) for m in metrics
            }
    return dict(out)
