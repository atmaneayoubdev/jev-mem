"""Pre-registered secondary analyses as extra "systems" computed from the same materials.

- budget sweep:   `<system>@<budget>` (same selection logic, smaller context budget)
- pool sweep:     `hybrid-jev#pool<P>` (first-stage pool size P)
- ablations:      `hybrid-jev~<step>` (policy ignores dimensions; judgments unchanged)
- write-only:     `embedding~lifecycle-only`: dense top-K on the Jev-lifecycle store, withholding
                   non-current memories, no read-time judge
- read-only:      `hybrid-jev~read-only`: Jev read-time judgments on a store *without* lifecycle
                   links (every memory "current")

Caveat recorded in the report: since q1.1 the judge's candidate state includes
`memory_status`, so dimension ablations remove the *policy's* use of a dimension while the
judge inputs stay fixed.
"""

from __future__ import annotations

from collections.abc import Sequence

from jevmem.benchmark.materials import CaseMaterials
from jevmem.benchmark.systems import SYSTEMS, Params, Selection, _baseline_context, select
from jevmem.memory.lineage import Validity, validity_at
from jevmem.policy.thresholds import Ablation

ABLATION_STEPS: dict[str, Ablation] = {
    "relevance-only": Ablation(
        utility=False, supersession=False, contradiction=False, temporal=False, intent=False
    ),
    "+utility": Ablation(
        utility=True, supersession=False, contradiction=False, temporal=False, intent=False
    ),
    "+supersession": Ablation(
        utility=True, supersession=True, contradiction=False, temporal=False, intent=True
    ),
    "+contradiction": Ablation(
        utility=True, supersession=True, contradiction=True, temporal=False, intent=True
    ),
    "+temporal (full)": Ablation(),
}

BUDGET_SYSTEMS = ("embedding", "rerank", "hybrid-jev", "hybrid-qwen")


def budget_variants(mat: CaseMaterials, params: Params, budgets: Sequence[int]) -> list[Selection]:
    out = []
    for budget in budgets:
        for name in BUDGET_SYSTEMS:
            spec = SYSTEMS[name]
            if spec.judge is not None and spec.judge not in mat.judged:
                continue
            sel = select(spec, mat, params, budget)
            out.append(sel.model_copy(update={"system": f"{name}@{budget}"}))
    return out


def pool_variants(
    mat: CaseMaterials, params: Params, budget: int, pools: Sequence[int]
) -> list[Selection]:
    if "jev" not in mat.judged:
        return []
    return [
        select(SYSTEMS["hybrid-jev"], mat, params, budget, pool=p).model_copy(
            update={"system": f"hybrid-jev#pool{p}"}
        )
        for p in pools
    ]


def ablation_variants(mat: CaseMaterials, params: Params, budget: int) -> list[Selection]:
    if "jev" not in mat.judged:
        return []
    out = []
    base = params.policy["jev"]
    for step, ablation in ABLATION_STEPS.items():
        policy = base.model_copy(update={"ablation": ablation})
        sel = select(SYSTEMS["hybrid-jev"], mat, params, budget, policy=policy)
        out.append(sel.model_copy(update={"system": f"hybrid-jev~{step}"}))
    out.append(_lifecycle_only(mat, params, budget))
    if "jev-readonly" in mat.judged:
        ro = mat.judged["jev-readonly"]
        view = CaseMaterials(
            case=mat.case,
            memories=mat.memories,
            store=mat.store,
            index=mat.index,
            rankings=mat.rankings,
            retrieval_ms=mat.retrieval_ms,
            judged={**mat.judged, "jev": ro},
            n_background=mat.n_background,
        )
        sel = select(SYSTEMS["hybrid-jev"], view, params, budget)
        out.append(sel.model_copy(update={"system": "hybrid-jev~read-only"}))
    return out


def _lifecycle_only(mat: CaseMaterials, params: Params, budget: int) -> Selection:
    """Dense top-K over the Jev-lifecycle store, withholding memories that are not current."""
    judged = mat.judged["jev"]
    ttl = params.policy["jev"].write.ttl()
    k = params.k["embedding"]
    ranking = mat.rankings.get("embedding", [])
    kept = [
        s.memory_id
        for s in ranking
        if not judged.store.get(s.memory_id).instruction_like
        and validity_at(judged.store.get(s.memory_id), judged.store, mat.case.now, ttl)
        is Validity.CURRENT
    ][:k]
    context = _baseline_context(mat, kept, budget)
    return Selection(
        system="embedding~lifecycle-only",
        selected_ids=context.memory_ids,
        ranked_ids=kept,
        context_text=context.text,
        context_tokens=context.tokens,
        retrieval_ms=mat.retrieval_ms.get("embedding", 0.0),
    )
