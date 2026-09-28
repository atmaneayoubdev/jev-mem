"""Calibrate every system's free parameters on the calib split (never on test).

Objective, identical for every system: mean memory-selection accuracy (all required
memories injected, no forbidden one), with judge failures counted as incorrect; ties are
broken by fewer context tokens, then by the smaller parameter value. Everything runs
offline over cached materials.

Not calibrated (fixed and documented): write-time thresholds (they change lifecycle links
and would require re-materialisation), the TTL table, and the UNCERTAIN band width δ,
which relabels only memories that are never injected and so cannot change selection.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel

from jevmem.benchmark.materials import CaseMaterials
from jevmem.benchmark.metrics import case_result
from jevmem.benchmark.systems import SYSTEMS, Params, Selection, SystemSpec, available, select
from jevmem.policy.thresholds import PolicyConfig

K_GRID = (1, 2, 3, 4, 5, 6, 8, 10)
HALF_LIFE_GRID = (15.0, 30.0, 60.0, 90.0, 180.0, 365.0, 730.0)
DUP_GRID = (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
TAU_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
INTENT_CONF_GRID = (0.3, 0.5, 0.7)


class GridPoint(BaseModel):
    system: str
    setting: dict[str, Any]
    selection_accuracy: float
    mean_tokens: float


class CalibrationReport(BaseModel):
    params: Params
    best: dict[str, GridPoint]
    grid: list[GridPoint]
    cases: int


def _score(
    materials: Sequence[CaseMaterials], run: Callable[[CaseMaterials], Selection]
) -> tuple[float, float]:
    correct, tokens = [], []
    for mat in materials:
        sel = run(mat)
        correct.append(case_result(mat.case, sel, None).selection_correct)
        tokens.append(sel.context_tokens)
    return float(np.mean(correct)), float(np.mean(tokens))


def _best(points: list[GridPoint]) -> GridPoint:
    return sorted(
        points, key=lambda p: (-p.selection_accuracy, p.mean_tokens, list(p.setting.values()))
    )[0]


def calibrate(
    materials: Sequence[CaseMaterials], budget: int, *, base: Params | None = None
) -> CalibrationReport:
    params = (base or Params()).model_copy(deep=True)
    names = {s.name for s in available(list(SYSTEMS), materials[0])}
    grid: list[GridPoint] = []
    best: dict[str, GridPoint] = {}

    def search(
        system: str, settings: list[dict[str, Any]], apply: Callable[[Params, dict[str, Any]], None]
    ) -> None:
        if system not in names:
            return
        points = []
        for setting in settings:
            trial = params.model_copy(deep=True)
            apply(trial, setting)
            spec = SYSTEMS[system]

            def run(m: CaseMaterials, t: Params = trial, spec: SystemSpec = spec) -> Selection:
                return select(spec, m, t, budget)

            acc, tok = _score(materials, run)
            points.append(
                GridPoint(system=system, setting=setting, selection_accuracy=acc, mean_tokens=tok)
            )
        grid.extend(points)
        best[system] = winner = _best(points)
        apply(params, winner.setting)

    def set_k(name: str) -> Callable[[Params, dict[str, Any]], None]:
        def apply(p: Params, s: dict[str, Any]) -> None:
            p.k[name] = s["k"]

        return apply

    for name in ("recency", "bm25", "embedding", "rerank"):
        search(name, [{"k": k} for k in K_GRID], set_k(name))

    for name, ranking in (("embedding-threshold", "embedding"), ("rerank-threshold", "rerank")):
        scores = [s.score for m in materials for s in m.rankings.get(ranking, [])[:20]]
        if scores:
            thetas = sorted(
                {round(float(q), 4) for q in np.quantile(scores, np.linspace(0.5, 0.995, 25))}
            )

            def apply_t(p: Params, s: dict[str, Any], name: str = name) -> None:
                p.threshold[name] = s["theta"]

            search(name, [{"theta": t} for t in thetas], apply_t)

    def apply_decay(p: Params, s: dict[str, Any]) -> None:
        p.half_life_days = s["half_life_days"]
        p.k["embedding-decay"] = s["k"]

    search(
        "embedding-decay",
        [{"half_life_days": h, "k": k} for h, k in itertools.product(HALF_LIFE_GRID, K_GRID)],
        apply_decay,
    )

    def apply_dup(p: Params, s: dict[str, Any]) -> None:
        p.duplicate_similarity = s["duplicate_similarity"]
        p.k["embedding-lifecycle"] = s["k"]

    search(
        "embedding-lifecycle",
        [{"duplicate_similarity": d, "k": k} for d, k in itertools.product(DUP_GRID, K_GRID)],
        apply_dup,
    )

    for judge, system in (("jev", "hybrid-jev"), ("qwen", "hybrid-qwen")):

        def apply_policy(p: Params, s: dict[str, Any], judge: str = judge) -> None:
            cfg = p.policy[judge].model_copy(deep=True)
            cfg.read.relevance = s["tau_r"]
            cfg.read.utility = s["tau_u"]
            cfg.read.intent_confidence = s["c_intent"]
            p.policy[judge] = PolicyConfig.model_validate(cfg.model_dump())

        settings = [
            {"tau_r": r, "tau_u": u, "c_intent": c}
            for r, u, c in itertools.product(TAU_GRID, TAU_GRID, INTENT_CONF_GRID)
        ]
        search(system, settings, apply_policy)

    return CalibrationReport(params=params, best=best, grid=grid, cases=len(materials))
