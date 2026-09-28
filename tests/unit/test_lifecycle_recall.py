"""Write pipeline + read pipeline end to end, with a scripted fake judge."""

from __future__ import annotations

from datetime import timedelta

import pytest

from jevmem.judgment.fake import FakeJudge, one_hot
from jevmem.judgment.questions import (
    DURABILITY_OPTIONS,
    HORIZON_OPTIONS,
    INTENT_OPTIONS,
    RELATION_OPTIONS,
)
from jevmem.memory.context import ContextBuilder, ContextEntry
from jevmem.memory.lifecycle import LifecyclePipeline
from jevmem.memory.lineage import Validity, validity_at
from jevmem.memory.models import LinkType, MemoryStatus
from jevmem.memory.recall import JudgedRecall
from jevmem.memory.store import InMemoryStore
from jevmem.policy.engine import Decision
from jevmem.policy.thresholds import PolicyConfig
from jevmem.retrieval.base import MemoryIndex
from jevmem.retrieval.retrievers import AllRetriever, BM25Retriever
from jevmem.timing import makespan
from tests.conftest import T0, MakeMemory

CONFIG = PolicyConfig()
RULES: dict[tuple[str, str], str] = {}


def pair_rule(earlier: str, later: str) -> dict[str, float]:
    return one_hot(RELATION_OPTIONS, RULES.get((earlier, later), "unrelated"), 0.95)


def profile_rule(memory: str) -> tuple[dict[str, float], dict[str, float]]:
    kind = "temporary" if "this week" in memory else "lasting"
    return one_hot(DURABILITY_OPTIONS, kind, 0.95), one_hot(HORIZON_OPTIONS, "weeks", 0.9)


def intent_rule(query: str) -> dict[str, float]:
    return one_hot(INTENT_OPTIONS, "historical" if "before" in query else "current", 0.95)


def judge(**kw: object) -> FakeJudge:
    return FakeJudge(pair=pair_rule, profile=profile_rule, intent=intent_rule, **kw)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    RULES.clear()


def pipeline(store: InMemoryStore, j: FakeJudge | None = None) -> LifecyclePipeline:
    return LifecyclePipeline(store, MemoryIndex(store), j or judge(), CONFIG)


AWS = "My preferred cloud provider is AWS."
AZURE = "We moved everything to Azure; Azure is now my preferred cloud provider."


async def test_supersession_links_and_status(store: InMemoryStore, make_memory: MakeMemory) -> None:
    RULES[(AWS, AZURE)] = "supersedes"
    reports = await pipeline(store).write_many(
        [make_memory(AZURE, 100, mid="azure"), make_memory(AWS, 0, mid="aws")]
    )
    assert [r.memory_id for r in reports] == ["aws", "azure"]  # sorted by observation time
    assert store.get("aws").status is MemoryStatus.SUPERSEDED
    assert store.get("azure").status is MemoryStatus.ACTIVE
    [link] = store.links_to("aws", [LinkType.SUPERSEDES])
    assert link.source_id == "azure"
    assert link.judge == "fake:fake"
    assert link.policy_version == CONFIG.version


async def test_writes_must_follow_observation_order(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    p = pipeline(store)
    await p.write(make_memory("later", 10))
    with pytest.raises(ValueError, match="older than the last write"):
        await p.write(make_memory("earlier", 1))


async def test_temporary_memory_only_overrides(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    home, trip = "I live in Berlin.", "I'm in Tokyo this week, not Berlin."
    RULES[(home, trip)] = "supersedes"
    await pipeline(store).write_many(
        [make_memory(home, 0, mid="home"), make_memory(trip, 30, mid="trip")]
    )
    assert store.get("home").status is MemoryStatus.ACTIVE
    [link] = store.links_to("home", [LinkType.TEMPORARILY_OVERRIDES])
    assert link.expires_at == T0 + timedelta(days=30 + 14)
    ttl = CONFIG.write.ttl()
    assert (
        validity_at(store.get("home"), store, T0 + timedelta(days=35), ttl) is Validity.OVERRIDDEN
    )
    assert validity_at(store.get("home"), store, T0 + timedelta(days=60), ttl) is Validity.CURRENT
    assert validity_at(store.get("trip"), store, T0 + timedelta(days=60), ttl) is Validity.EXPIRED


async def test_supersession_propagates_across_duplicates(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    w1, w2, aisle = (
        "I like window seats.",
        "Window seats are my favourite seats.",
        "I switched to aisle seats.",
    )
    RULES[(w1, w2)] = "duplicate"
    RULES[(w2, aisle)] = "supersedes"  # (w1, aisle) stays "unrelated": propagation must catch it
    report = (
        await pipeline(store).write_many(
            [
                make_memory(w1, 0, mid="w1"),
                make_memory(w2, 5, mid="w2"),
                make_memory(aisle, 9, mid="aisle"),
            ]
        )
    )[-1]
    assert store.get("w2").status is MemoryStatus.SUPERSEDED
    assert store.get("w1").status is MemoryStatus.SUPERSEDED
    assert report.propagated_ids == ["w1"]


async def test_revert_does_not_inherit_superseded(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    back = "Back to AWS: my preferred cloud provider is AWS again."
    RULES[(AWS, AZURE)] = "supersedes"
    RULES[(AZURE, back)] = "supersedes"
    RULES[(AWS, back)] = "duplicate"
    await pipeline(store).write_many(
        [
            make_memory(AWS, 0, mid="aws"),
            make_memory(AZURE, 50, mid="azure"),
            make_memory(back, 100, mid="back"),
        ]
    )
    assert store.get("back").status is MemoryStatus.ACTIVE
    assert store.get("azure").status is MemoryStatus.SUPERSEDED
    assert store.get("aws").status is MemoryStatus.SUPERSEDED
    assert store.links_from("back", [LinkType.REINFORCES])[0].target_id == "aws"


async def test_judge_failure_marks_pending_then_rejudges(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    RULES[(AWS, AZURE)] = "supersedes"
    j = judge()
    p = pipeline(store, j)
    await p.write(make_memory(AWS, 0, mid="aws"))
    j.fail = True
    report = await p.write(make_memory(AZURE, 100, mid="azure"))
    assert report.pending
    assert store.get("azure").lifecycle_pending
    assert store.get("aws").status is MemoryStatus.ACTIVE
    j.fail = False
    [redo] = await p.rejudge_pending("u1")
    assert redo.neighbor_ids == ["aws"]  # still only earlier memories
    assert store.get("aws").status is MemoryStatus.SUPERSEDED
    assert not store.get("azure").lifecycle_pending


async def test_neighbors_prefer_active_then_few_superseded(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    p = LifecyclePipeline(
        store, MemoryIndex(store), None, CONFIG, active_neighbors=1, superseded_neighbors=1
    )
    for i, status in enumerate(
        [MemoryStatus.SUPERSEDED, MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE]
    ):
        await p.write(make_memory(f"cloud provider note {i}", i, mid=f"n{i}", status=status))
    ids = [m.id for m in p.neighbors(make_memory("cloud provider question", 10))]
    assert ids[0] == "n2"
    assert len(ids) == 2


# --- read path ---------------------------------------------------------------------


async def _two_version_store(store: InMemoryStore, make_memory: MakeMemory) -> MemoryIndex:
    RULES[(AWS, AZURE)] = "supersedes"
    index = MemoryIndex(store)
    p = LifecyclePipeline(store, index, judge(), CONFIG)
    await p.write_many(
        [
            make_memory(AWS, 0, mid="aws"),
            make_memory("My sister lives in Lisbon.", 10, mid="sis"),
            make_memory(AZURE, 100, mid="azure"),
        ]
    )
    return index


def _recall(store: InMemoryStore, index: MemoryIndex, j: FakeJudge, **kw: object) -> JudgedRecall:
    return JudgedRecall(store, AllRetriever(index), j, CONFIG, **kw)  # type: ignore[arg-type]


def cloud_candidate(query: str, memory: str) -> tuple[float, float]:
    return (0.95, 0.9) if ("cloud" in memory or "Azure" in memory) else (0.05, 0.05)


async def test_current_query_uses_latest_only(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    index = await _two_version_store(store, make_memory)
    result = await _recall(store, index, judge(candidate=cloud_candidate)).recall(
        "Deploy my service on my preferred cloud.", "u1", T0 + timedelta(days=200)
    )
    decisions = {d.memory_id: d.decision for d in result.decisions}
    assert decisions == {"aws": Decision.STALE, "azure": Decision.USE, "sis": Decision.DROP}
    assert result.selected_ids == ["azure"]
    assert result.judge_used
    assert result.judge_calls == 4  # intent + 3 candidates


async def test_historical_query_renders_timeline(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    index = await _two_version_store(store, make_memory)
    result = await _recall(store, index, judge(candidate=cloud_candidate)).recall(
        "Which cloud did I prefer before Azure?", "u1", T0 + timedelta(days=200)
    )
    assert result.intent is not None
    assert result.intent.intent == "historical"
    assert sorted(result.selected_ids) == ["aws", "azure"]
    [item] = result.context.items
    assert item.text.startswith("- Timeline (older → newer): [2026-01-02]")
    assert "(replaced)" in item.text
    assert "(current)" in item.text


async def test_expansion_recovers_successor_missed_by_retrieval(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    index = await _two_version_store(store, make_memory)
    recall = JudgedRecall(
        store, BM25Retriever(index), judge(candidate=cloud_candidate), CONFIG, pool_size=1
    )
    result = await recall.recall("which provider is preferred", "u1", T0 + timedelta(days=200))
    assert [(c.memory.id, c.sources) for c in result.candidates][:2] == [
        ("aws", ["bm25"]),
        ("azure", ["link:successor"]),
    ]
    assert result.selected_ids == ["azure"]


async def test_fallback_when_judge_is_down(store: InMemoryStore, make_memory: MakeMemory) -> None:
    index = await _two_version_store(store, make_memory)
    result = await _recall(store, index, judge(fail=True), fallback_k=2).recall(
        "Deploy on my preferred cloud.", "u1", T0 + timedelta(days=200)
    )
    assert not result.judge_used
    assert result.fallback_reason is not None
    assert "intent judgment failed" in result.fallback_reason
    assert {d.decision for d in result.decisions} == {Decision.UNJUDGED, Decision.DROP}
    assert result.judgments == {}
    assert "possibly outdated" in result.context.text or "aws" not in result.selected_ids


async def test_conflicts_render_as_one_unit(store: InMemoryStore, make_memory: MakeMemory) -> None:
    veg, steak = "I am strictly vegetarian.", "I am not vegetarian; I eat steak every weekend."
    RULES[(veg, steak)] = "contradicts"
    index = MemoryIndex(store)
    await LifecyclePipeline(store, index, judge(), CONFIG).write_many(
        [make_memory(veg, 0, mid="veg"), make_memory(steak, 5, mid="steak")]
    )
    result = await _recall(store, index, judge(candidate=lambda q, m: (0.9, 0.9))).recall(
        "Plan my dinner.", "u1", T0 + timedelta(days=10)
    )
    assert {d.decision for d in result.decisions} == {Decision.CONFLICT}
    [item] = result.context.items
    assert item.text.startswith("- Conflicting memories (unresolved):")


def test_context_dedupes_reinforcing_duplicates_and_respects_budget(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    from jevmem.memory.models import MemoryLink

    a, b, c = (
        make_memory("I like window seats.", 0, mid="a"),
        make_memory("Window seats please.", 5, mid="b"),
        make_memory("x" * 400, 6, mid="c"),
    )
    for m in (a, b, c):
        store.add(m)
    store.add_link(
        MemoryLink(link_type=LinkType.REINFORCES, source_id="b", target_id="a", judge="t")
    )
    entries = [
        ContextEntry(memory=m, priority=p, label="use") for m, p in ((a, 0.9), (b, 0.8), (c, 0.7))
    ]
    result = ContextBuilder(store, budget=60).build(entries)
    assert result.deduplicated == ["a"]
    assert result.memory_ids == ["b"]
    assert result.skipped_for_budget == ["c"]
    assert result.tokens <= 60
    assert ContextBuilder(store, budget=60).build([]).text == ""


def test_makespan() -> None:
    assert makespan([], 4) == 0.0
    assert makespan([100, 100, 100, 100], 4) == 100
    assert makespan([100, 100, 100, 100], 2) == 200
    assert makespan([300, 100, 100], 2) == 300


async def test_bm25_only_neighbors_miss_lexically_disjoint_pairs(
    store: InMemoryStore, make_memory: MakeMemory
) -> None:
    """Known limitation, measured by the benchmark: without embeddings, write-time neighbour
    search only finds memories that share terms, so disjoint rephrasings are never paired."""
    p = pipeline(store)
    await p.write(make_memory("I drive a Toyota Corolla.", 0, mid="toyota"))
    report = await p.write(
        make_memory("Bought a Kia Sportage; it's my daily car now.", 30, mid="kia")
    )
    assert report.neighbor_ids == []
