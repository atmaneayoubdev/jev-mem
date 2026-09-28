"""SqlMemoryStore satisfies the MemoryStore contract and runs the real lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jevmem.database.repository import SqlMemoryStore, TurnStore
from jevmem.database.session import init_db, make_engine, make_sessionmaker
from jevmem.judgment.fake import FakeJudge, one_hot
from jevmem.judgment.questions import RELATION_OPTIONS
from jevmem.memory.lifecycle import LifecyclePipeline
from jevmem.memory.models import LinkType, Memory, MemoryLink, MemoryStatus
from jevmem.memory.store import MemoryNotFoundError
from jevmem.policy.thresholds import PolicyConfig
from jevmem.retrieval.base import MemoryIndex

T0 = datetime(2026, 1, 1, 9, tzinfo=UTC)


@pytest.fixture
def sql(tmp_path: Path) -> tuple[SqlMemoryStore, TurnStore]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    sessions = make_sessionmaker(engine)
    return SqlMemoryStore(sessions), TurnStore(sessions)


def mem(mid: str, content: str, days: float = 0, **kw: object) -> Memory:
    return Memory.model_validate(
        {
            "id": mid,
            "user_id": "u",
            "content": content,
            "observed_at": T0 + timedelta(days=days),
            **kw,
        }
    )


def test_roundtrip_ordering_and_timezones(sql: tuple[SqlMemoryStore, TurnStore]) -> None:
    store, _ = sql
    store.add(mem("b", "later", 5, tags=["x"], metadata={"k": 1}))
    store.add(mem("a", "earlier", 1))
    got = store.get("b")
    assert got.observed_at.tzinfo is not None
    assert got.observed_at == T0 + timedelta(days=5)
    assert (got.tags, got.metadata) == (["x"], {"k": 1})
    assert [m.id for m in store.list_memories("u")] == ["a", "b"]
    got.status = MemoryStatus.SUPERSEDED
    store.update(got)
    assert [m.id for m in store.list_memories("u", [MemoryStatus.ACTIVE])] == ["a"]
    with pytest.raises(ValueError, match="already exists"):
        store.add(mem("a", "dup"))
    with pytest.raises(MemoryNotFoundError):
        store.get("zzz")
    assert store.users() == ["u"]


def test_links_and_reset(sql: tuple[SqlMemoryStore, TurnStore]) -> None:
    store, turns = sql
    store.add(mem("a", "a"))
    store.add(mem("b", "b", 1))
    store.add_link(
        MemoryLink(
            link_type=LinkType.SUPERSEDES, source_id="b", target_id="a", judge="t", expires_at=T0
        )
    )
    [link] = store.links_to("a", [LinkType.SUPERSEDES])
    assert link.source_id == "b"
    assert link.expires_at == T0
    assert store.links_from("b", [LinkType.CONFLICTS_WITH]) == []
    assert len(store.all_links("u")) == 1
    turns.add("c1", "u", "user", "hello")
    assert [t["content"] for t in turns.history("c1")] == ["hello"]
    assert store.delete_user("u") == 2
    assert store.list_memories("u") == []
    assert turns.history("c1") == []


async def test_lifecycle_runs_against_sql_store(sql: tuple[SqlMemoryStore, TurnStore]) -> None:
    store, _ = sql
    aws, azure = "My preferred cloud is AWS.", "We moved to Azure; Azure is my preferred cloud now."

    def pair(e: str, later: str) -> dict[str, float]:
        return one_hot(
            RELATION_OPTIONS, "supersedes" if (e, later) == (aws, azure) else "unrelated", 0.95
        )

    pipeline = LifecyclePipeline(store, MemoryIndex(store), FakeJudge(pair=pair), PolicyConfig())
    await pipeline.write_many([mem("aws", aws, 0), mem("azure", azure, 100)])
    assert store.get("aws").status is MemoryStatus.SUPERSEDED
    assert store.get("azure").durability is not None
    assert store.links_to("aws", [LinkType.SUPERSEDES])[0].source_id == "azure"
