from __future__ import annotations

import pytest

from jevmem.benchmark.reliability import relation_calibration, reliability
from jevmem.timing import makespan


def test_reliability_perfect_and_overconfident() -> None:
    perfect = reliability("p", [0.05, 0.05, 0.95, 0.95], [0, 0, 1, 1])
    assert perfect.ece == pytest.approx(0.05)
    over = reliability("o", [0.99] * 4, [1, 0, 0, 0])
    assert over.ece == pytest.approx(0.74)
    assert over.brier is not None
    assert over.brier > 0.5
    assert reliability("e", [], []).n == 0
    assert sum(b.count for b in perfect.bins) == 4


def test_relation_calibration_uses_top_choice() -> None:
    rows = [
        {
            "judge": "jev",
            "gold": "supersedes",
            "probabilities": {"supersedes": 0.9, "unrelated": 0.1},
        },
        {
            "judge": "jev",
            "gold": "contradicts",
            "probabilities": {"supersedes": 0.8, "contradicts": 0.2},
        },
        {"judge": "qwen", "gold": "supersedes", "probabilities": None},
    ]
    res = relation_calibration(rows, "jev")
    assert res.n == 2
    assert res.ece == pytest.approx((abs(0.9 - 1) + abs(0.8 - 0)) / 2)


def test_makespan_is_monotone_in_workers() -> None:
    lat = [300.0, 200.0, 100.0, 100.0]
    assert makespan(lat, 1) == 700
    assert makespan(lat, 4) == 300
    assert makespan(lat, 2) <= makespan(lat, 1)


@pytest.mark.parametrize("name", ["rows.jsonl", "rows.jsonl.gz"])
def test_read_jsonl_keeps_unicode_line_separators(tmp_path, name: str) -> None:
    import gzip
    import json

    from jevmem.benchmark.reports import read_jsonl

    rows = [{"id": 1, "text": "before\u2028after\x85end"}, {"id": 2, "text": "plain"}]
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path = tmp_path / name
    if name.endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    else:
        path.write_text(body, encoding="utf-8", newline="\n")
    assert read_jsonl(path) == rows
