"""Nondeterminism check: re-issue Jev read-time judgments without the cache and compare.

For each case, the candidate pool and intent judgments of the cached materials are re-judged
by an uncached client (same pinned model, same states). Reported: mean |Δ| of relevance and
utility, the fraction of policy decisions that flip under the calibrated policy, and the
fraction of cases whose selected context changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel

from jevmem.benchmark.materials import CaseMaterials
from jevmem.benchmark.systems import SYSTEMS, Params, select
from jevmem.judgment.jev_judge import JevJudge
from jevmem.memory.recall import candidate_facts


class NondeterminismReport(BaseModel):
    cases: int
    judgments: int
    mean_abs_delta_relevance: float
    mean_abs_delta_utility: float
    max_abs_delta: float
    intent_choice_changed: float
    decision_flip_rate: float
    selection_changed_rate: float
    resolved_models: list[str]


async def check(
    materials: Sequence[CaseMaterials], judge: JevJudge, params: Params, budget: int
) -> NondeterminismReport:
    d_rel, d_util, intent_changed, flips, decisions, changed = [], [], [], 0, 0, 0
    models: set[str] = set()
    spec = SYSTEMS["hybrid-jev"]
    for mat in materials:
        judged = mat.judged["jev"]
        if judged.failure or judged.intent is None:
            continue
        before = select(spec, mat, params, budget)
        ids = before.expanded_ids
        states = [
            (
                mid,
                candidate_facts(
                    judged.store, judged.store.get(mid), mat.case.now, params.policy["jev"]
                ).validity.value,
            )
            for mid in ids
        ]
        fresh = await asyncio.gather(
            *(
                judge.candidate(mat.case.query, judged.store.get(mid).content, status)
                for mid, status in states
            )
        )
        new_intent = await judge.intent(mat.case.query)
        models.update(j.meta.model for j in fresh)
        intent_changed.append(float(new_intent.intent.choice != judged.intent.intent.choice))
        replaced = dict(judged.candidates)
        for (mid, _), j in zip(states, fresh, strict=True):
            old = judged.candidates[mid]
            d_rel.append(abs(old.relevance - j.relevance))
            d_util.append(abs(old.utility - j.utility))
            replaced[mid] = j
        original_candidates, original_intent = judged.candidates, judged.intent
        judged.candidates, judged.intent = replaced, new_intent
        after = select(spec, mat, params, budget)
        judged.candidates, judged.intent = original_candidates, original_intent
        for mid in ids:
            decisions += 1
            flips += int(before.decisions.get(mid) != after.decisions.get(mid))
        changed += int(set(before.selected_ids) != set(after.selected_ids))
    n_cases = len(intent_changed)
    return NondeterminismReport(
        cases=n_cases,
        judgments=len(d_rel),
        mean_abs_delta_relevance=float(np.mean(d_rel)) if d_rel else 0.0,
        mean_abs_delta_utility=float(np.mean(d_util)) if d_util else 0.0,
        max_abs_delta=float(max([*d_rel, *d_util], default=0.0)),
        intent_choice_changed=float(np.mean(intent_changed)) if intent_changed else 0.0,
        decision_flip_rate=flips / decisions if decisions else 0.0,
        selection_changed_rate=changed / n_cases if n_cases else 0.0,
        resolved_models=sorted(models),
    )
