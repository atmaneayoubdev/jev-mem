"""Leakage probe: can a bag-of-words classifier solve the benchmark from surface cues?

A logistic regression over TF-IDF features of (query, memory) text is trained on one split
and evaluated on another. If this probe's memory-selection accuracy approaches the judged
systems', the benchmark is measuring template artefacts rather than judgment, and the report
must say so. Requires the `bench` extra (scikit-learn).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel

from jevmem.benchmark.datasets.schema import Case


class ProbeResult(BaseModel):
    train_split: str
    eval_split: str
    auc: float | None
    memory_accuracy: float
    selection_accuracy: float  # per case: all required selected and no forbidden selected
    cases: int


def _rows(
    cases: Sequence[Case],
) -> tuple[list[str], list[str], list[int], list[tuple[str, str, str]]]:
    queries: list[str] = []
    memories: list[str] = []
    labels: list[int] = []
    keys: list[tuple[str, str, str]] = []
    for case in cases:
        for m in case.memories:
            queries.append(case.query)
            memories.append(m.content)
            labels.append(int(m.label == "required"))
            keys.append((case.case_id, m.id, m.label))
    return queries, memories, labels, keys


def run_probe(train: Sequence[Case], evaluate: Sequence[Case]) -> ProbeResult:
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    q_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    m_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    tq, tm, ty, _ = _rows(train)
    eq, em, ey, keys = _rows(evaluate)
    x_train = hstack([q_vec.fit_transform(tq), m_vec.fit_transform(tm)]).tocsr()
    x_eval = hstack([q_vec.transform(eq), m_vec.transform(em)]).tocsr()
    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(x_train, ty)
    proba = model.predict_proba(x_eval)[:, 1]
    predicted = proba >= 0.5
    auc = float(roc_auc_score(ey, proba)) if len(set(ey)) > 1 else None

    per_case: dict[str, list[tuple[str, bool]]] = {}
    for (case_id, _mid, label), selected in zip(keys, predicted, strict=True):
        per_case.setdefault(case_id, []).append((label, bool(selected)))
    correct = [
        all(sel for label, sel in rows if label == "required")
        and not any(sel for label, sel in rows if label == "forbidden")
        for rows in per_case.values()
    ]
    return ProbeResult(
        train_split=train[0].split if train else "",
        eval_split=evaluate[0].split if evaluate else "",
        auc=auc,
        memory_accuracy=float(np.mean(predicted == np.array(ey, dtype=bool))),
        selection_accuracy=float(np.mean(correct)),
        cases=len(per_case),
    )
