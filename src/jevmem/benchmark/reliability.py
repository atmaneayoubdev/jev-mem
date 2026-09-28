"""Calibration of judge probabilities against gold labels (ECE + reliability bins).

- Utility: for every memory a judged system scored, the gold label is 1 if the memory is
  *required* for the case and 0 otherwise (forbidden, neutral, background). Reported both over
  all judged candidates and over case memories only (background distractors are easy negatives
  that would otherwise dominate).
- Relation: for gold write-time pairs the judge compared, confidence = p(top choice),
  correct = (top choice == gold relation).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel


class ReliabilityBin(BaseModel):
    lo: float
    hi: float
    count: int
    mean_confidence: float | None
    accuracy: float | None


class CalibrationResult(BaseModel):
    name: str
    n: int
    ece: float | None
    brier: float | None
    bins: list[ReliabilityBin]


def reliability(
    name: str, probs: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> CalibrationResult:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    if p.size == 0:
        return CalibrationResult(name=name, n=0, ece=None, brier=None, bins=[])
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    bins, ece = [], 0.0
    for b in range(n_bins):
        mask = idx == b
        count = int(mask.sum())
        conf = float(p[mask].mean()) if count else None
        acc = float(y[mask].mean()) if count else None
        if count and conf is not None and acc is not None:
            ece += count / p.size * abs(conf - acc)
        bins.append(
            ReliabilityBin(
                lo=float(edges[b]),
                hi=float(edges[b + 1]),
                count=count,
                mean_confidence=conf,
                accuracy=acc,
            )
        )
    return CalibrationResult(
        name=name, n=int(p.size), ece=float(ece), brier=float(np.mean((p - y) ** 2)), bins=bins
    )


def utility_calibration(
    rows: Iterable[dict[str, Any]], cases: dict[str, dict[str, Any]], system: str
) -> list[CalibrationResult]:
    """rows: parsed cases.jsonl records; cases: case_id -> case dict (with memory labels)."""
    all_p, all_y, case_p, case_y = [], [], [], []
    for row in rows:
        if row["system"] != system or row["failed"]:
            continue
        labels = {m["id"]: m["label"] for m in cases[row["case_id"]]["memories"]}
        for mid, (_rel, util) in row["selection"].get("scores", {}).items():
            y = int(labels.get(mid) == "required")
            all_p.append(util)
            all_y.append(y)
            if mid in labels:
                case_p.append(util)
                case_y.append(y)
    return [
        reliability(f"{system} utility (all candidates)", all_p, all_y),
        reliability(f"{system} utility (case memories)", case_p, case_y),
    ]


def relation_calibration(relations: Iterable[dict[str, Any]], judge: str) -> CalibrationResult:
    probs, correct = [], []
    for r in relations:
        if r["judge"] != judge or not r.get("probabilities"):
            continue
        dist = r["probabilities"]
        top = max(dist, key=lambda k: dist[k])
        probs.append(dist[top])
        correct.append(int(top == r["gold"]))
    return reliability(f"{judge} relation (top-choice)", probs, correct)
