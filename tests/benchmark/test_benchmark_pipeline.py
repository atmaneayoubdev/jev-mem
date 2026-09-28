"""Offline benchmark pipeline: materialize → select → metrics, with the fake judge."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jevmem.benchmark.datasets.background import BackgroundMemory, with_background
from jevmem.benchmark.datasets.schema import ExpectedAnswer
from jevmem.benchmark.datasets.synthetic.generate import build_split, dataset_hash, families
from jevmem.benchmark.materials import Resources, materialize
from jevmem.benchmark.metrics import aggregate, case_result, lifecycle_outcomes
from jevmem.benchmark.scoring import AgentAnswer, score_answer
from jevmem.benchmark.stats import cluster_bootstrap, paired_cluster_bootstrap
from jevmem.benchmark.systems import SYSTEMS, Params, available, select
from jevmem.judgment.fake import FakeJudge, one_hot
from jevmem.judgment.questions import RELATION_OPTIONS
from jevmem.policy.thresholds import PolicyConfig

BACKGROUND = [
    BackgroundMemory(
        id=f"bg{i:04d}",
        content=f"I enjoy origami figure number {i}.",
        position=(i + 1) / 12,
        topic="origami",
    )
    for i in range(10)
]


def test_dataset_is_deterministic_and_split_by_family() -> None:
    dev_a, dev_b = build_split("dev"), build_split("dev")
    assert dataset_hash(dev_a) == dataset_hash(dev_b)
    calib = build_split("calib")
    assert not ({c.family for c in dev_a} & {c.family for c in calib})
    assert len({c.case_id for c in dev_a}) == len(dev_a)
    assert len(families("dev")) == 22
    for case in dev_a:
        assert case.now > max(m.observed_at for m in case.memories)
        assert {m.label for m in case.memories} <= {"required", "forbidden", "neutral"}


def test_background_interleaves_in_fixed_relative_order() -> None:
    case = build_split("dev")[0]
    merged = with_background(case, BACKGROUND, 5)
    bg = [m for m in merged if m.id.startswith("bg")]
    assert [m.id for m in bg] == [f"bg{i:04d}" for i in range(5)]
    start = min(m.observed_at for m in case.memories)
    assert all(start < m.observed_at < case.now for m in bg)
    assert with_background(case, BACKGROUND, 0) == list(case.memories)


def supersede_rule(earlier: str, later: str) -> dict[str, float]:
    kind = "supersedes" if "migrating" in later and "preferred cloud" in earlier else "unrelated"
    return one_hot(RELATION_OPTIONS, kind, 0.95)


async def test_materialize_select_and_score_offline() -> None:
    case = next(c for c in build_split("dev") if c.family == "supersession/cloud-migration")
    judge = FakeJudge(
        pair=supersede_rule,
        candidate=lambda q, m: (
            (0.9, 0.9) if "cloud" in m.lower() or "deploy" in m.lower() else (0.1, 0.1)
        ),
    )
    resources = Resources(
        judges={"jev": judge},
        embedder=None,
        reranker=None,
        background=BACKGROUND,
        write_policy=PolicyConfig(),
    )
    mat = await materialize(case, resources, n_background=10, pool_max=20)

    assert len(mat.memories) == len(case.memories) + 10
    assert mat.judged["jev"].failure is None
    specs = available(list(SYSTEMS), mat)
    assert {s.name for s in specs} == {"recency", "bm25", "bm25-jev"}  # no embeddings here

    params = Params()
    jev = select(SYSTEMS["bm25-jev"], mat, params, budget=1024)
    assert jev.judge_used
    assert jev.decisions["m1"] == "stale"
    assert "m3" in jev.selected_ids
    assert "m1" not in jev.selected_ids
    assert jev.judge_calls == 1 + len(jev.expanded_ids)

    answer_good = AgentAnswer(final_answer=case.expected.aliases[0])
    from jevmem.benchmark.answer import AnswerResult

    result = case_result(
        case,
        jev,
        AnswerResult(
            answer=answer_good,
            latency_ms=100.0,
            prompt_tokens=10,
            completion_tokens=5,
            cached=False,
        ),
    )
    assert result.selection_correct
    assert result.score is not None
    assert result.score.correct
    assert result.end_to_end_ms is not None

    relations, _ = lifecycle_outcomes(case, mat.judged["jev"])
    by_pair = {(r.earlier, r.later): r.predicted for r in relations}
    assert by_pair[("m1", "m3")] == "supersedes"

    bm25 = select(SYSTEMS["bm25"], mat, params, budget=1024, k_override=1)
    assert len(bm25.selected_ids) == 1
    agg = aggregate([result, case_result(case, bm25, None)], n_boot=50)
    assert agg["bm25-jev"]["selection_correct"].mean == 1.0


async def test_judge_failure_is_flagged_not_faked() -> None:
    case = build_split("dev")[0]
    resources = Resources(
        judges={"jev": FakeJudge(fail=True)},
        embedder=None,
        reranker=None,
        background=BACKGROUND,
        write_policy=PolicyConfig(),
    )
    mat = await materialize(case, resources, n_background=2, pool_max=5)
    assert mat.judged["jev"].failure is not None
    sel = select(SYSTEMS["bm25-jev"], mat, Params(), budget=512)
    assert sel.failure is not None
    assert sel.selected_ids == []
    assert case_result(case, sel, None).failed


@pytest.mark.parametrize(
    ("answer", "expected", "correct", "forbidden"),
    [
        (
            AgentAnswer(final_answer="Azure"),
            ExpectedAnswer(aliases=["Azure"], forbidden=["AWS"]),
            True,
            False,
        ),
        (
            AgentAnswer(final_answer="AWS"),
            ExpectedAnswer(aliases=["Azure"], forbidden=["AWS"]),
            False,
            True,
        ),
        (
            AgentAnswer(final_answer="Deploy on GCP"),
            ExpectedAnswer(aliases=["Google Cloud"]),
            True,
            False,
        ),
        (AgentAnswer(final_answer="Dr. Patel"), ExpectedAnswer(aliases=["Dr. Patel"]), True, False),
        (AgentAnswer(final_answer="Pineapple"), ExpectedAnswer(aliases=["apple"]), False, False),
        (
            AgentAnswer(final_answer="accessible entrance"),
            ExpectedAnswer(aliases=["accessib*"]),
            True,
            False,
        ),
        (AgentAnswer(final_answer="", abstain=True), ExpectedAnswer(mode="abstain"), True, False),
        (
            AgentAnswer(final_answer="O negative"),
            ExpectedAnswer(mode="conflict", aliases=["A positive", "O negative"]),
            False,
            False,
        ),
        (
            AgentAnswer(final_answer="O negative", conflict=True),
            ExpectedAnswer(mode="conflict", aliases=["A positive", "O negative"]),
            True,
            False,
        ),
        (
            AgentAnswer(final_answer="A positive or O negative"),
            ExpectedAnswer(mode="conflict", aliases=["A positive", "O negative"]),
            True,
            False,
        ),
    ],
)
def test_answer_scoring(
    answer: AgentAnswer, expected: ExpectedAnswer, correct: bool, forbidden: bool
) -> None:
    score = score_answer(answer, expected)
    assert (score.correct, score.forbidden_used) == (correct, forbidden)


def test_cluster_bootstrap_and_paired() -> None:
    est = cluster_bootstrap({"f1": [1, 1, 1], "f2": [0, 0, 0], "f3": [1, 0, 1]}, n_boot=500)
    assert est.mean == pytest.approx(5 / 9)
    assert est.lo is not None
    assert est.hi is not None
    assert est.lo <= est.mean <= est.hi
    assert cluster_bootstrap({}).mean is None
    paired = paired_cluster_bootstrap(
        {"a": [1, 1], "b": [1, 0], "c": [1, 1]}, {"a": [0, 1], "b": [0, 0], "c": [1, 0]}, n_boot=500
    )
    assert paired.diff == pytest.approx(5 / 6 - 2 / 6)
    assert paired.lo <= paired.diff <= paired.hi
    assert 0.0 <= paired.p_not_better <= 1.0
    _ = datetime.now(UTC)
