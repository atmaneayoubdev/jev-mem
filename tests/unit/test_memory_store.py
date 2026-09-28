from __future__ import annotations

from datetime import timedelta

import pytest

from jevmem.memory.lineage import (
    Validity,
    chain_head,
    conflict_partners,
    expires_at,
    predecessors,
    reinforce_cluster,
    successors,
    supersession_chain,
    validity_at,
)
from jevmem.memory.models import Durability, Horizon, LinkType, MemoryLink, MemoryStatus
from jevmem.memory.store import InMemoryStore, MemoryNotFoundError
from tests.conftest import T0, MakeMemory

TTL = {
    Horizon.DAYS: timedelta(days=3),
    Horizon.WEEKS: timedelta(days=14),
    Horizon.MONTHS: timedelta(days=120),
}


def _link(kind: LinkType, source: str, target: str, **kw: object) -> MemoryLink:
    return MemoryLink.model_validate(
        {"link_type": kind, "source_id": source, "target_id": target, "judge": "test", **kw}
    )


def test_store_returns_copies(store: InMemoryStore, make_memory: MakeMemory) -> None:
    m = make_memory("I prefer AWS.", mid="aws")
    store.add(m)
    fetched = store.get("aws")
    fetched.content = "mutated"
    assert store.get("aws").content == "I prefer AWS."


def test_list_is_ordered_and_filterable(store: InMemoryStore, make_memory: MakeMemory) -> None:
    store.add(make_memory("later", 5, mid="b"))
    store.add(make_memory("earlier", 1, mid="a"))
    store.add(make_memory("same time, higher sequence", 5, mid="c", sequence=1))
    assert [m.id for m in store.list_memories("u1")] == ["a", "b", "c"]
    old = store.get("a")
    old.status = MemoryStatus.SUPERSEDED
    store.update(old)
    assert [m.id for m in store.list_memories("u1", [MemoryStatus.ACTIVE])] == ["b", "c"]
    assert store.list_memories("someone-else") == []


def test_duplicate_add_and_missing_ids_raise(store: InMemoryStore, make_memory: MakeMemory) -> None:
    store.add(make_memory("x", mid="x"))
    with pytest.raises(ValueError, match="already exists"):
        store.add(make_memory("x", mid="x"))
    with pytest.raises(MemoryNotFoundError):
        store.get("nope")
    with pytest.raises(MemoryNotFoundError):
        store.add_link(_link(LinkType.SUPERSEDES, "x", "nope"))


def test_supersession_chain_and_head(store: InMemoryStore, make_memory: MakeMemory) -> None:
    for mid, day in (("aws", 0), ("gcp", 50), ("azure", 100)):
        store.add(make_memory(mid, day, mid=mid))
    store.add_link(_link(LinkType.SUPERSEDES, "gcp", "aws"))
    store.add_link(_link(LinkType.SUPERSEDES, "azure", "gcp"))
    for mid in ("aws", "gcp"):
        m = store.get(mid)
        m.status = MemoryStatus.SUPERSEDED
        store.update(m)

    assert [m.id for m in supersession_chain(store, "gcp")] == ["aws", "gcp", "azure"]
    assert chain_head(store, "aws").id == "azure"
    assert [m.id for m in successors(store, "aws")] == ["gcp"]
    assert [m.id for m in predecessors(store, "azure")] == ["gcp"]


def test_clusters_and_conflicts(store: InMemoryStore, make_memory: MakeMemory) -> None:
    for mid in ("w1", "w2", "w3", "veg", "meat"):
        store.add(make_memory(mid, mid=mid))
    store.add_link(_link(LinkType.REINFORCES, "w2", "w1"))
    store.add_link(_link(LinkType.REINFORCES, "w3", "w2"))
    store.add_link(_link(LinkType.CONFLICTS_WITH, "meat", "veg"))
    assert {m.id for m in reinforce_cluster(store, "w3")} == {"w1", "w2", "w3"}
    assert [m.id for m in conflict_partners(store, "veg")] == ["meat"]
    assert [m.id for m in conflict_partners(store, "meat")] == ["veg"]


def test_validity_temporary_expiry(store: InMemoryStore, make_memory: MakeMemory) -> None:
    paris = make_memory(
        "I'm in Paris this week.",
        mid="paris",
        durability=Durability.TEMPORARY,
        horizon=Horizon.WEEKS,
    )
    store.add(paris)
    assert expires_at(paris, TTL) == T0 + timedelta(days=14)
    assert validity_at(paris, store, T0 + timedelta(days=13), TTL) is Validity.CURRENT
    assert validity_at(paris, store, T0 + timedelta(days=14), TTL) is Validity.EXPIRED


def test_explicit_valid_until_beats_ttl(store: InMemoryStore, make_memory: MakeMemory) -> None:
    m = make_memory("x", durability=Durability.LASTING, valid_until=T0 + timedelta(days=1))
    store.add(m)
    assert validity_at(m, store, T0 + timedelta(days=2), TTL) is Validity.EXPIRED


def test_temporary_override_lapses(store: InMemoryStore, make_memory: MakeMemory) -> None:
    home = make_memory("I live in Berlin.", 0, mid="home", durability=Durability.LASTING)
    trip = make_memory(
        "I'm in Tokyo this week.",
        30,
        mid="trip",
        durability=Durability.TEMPORARY,
        horizon=Horizon.WEEKS,
    )
    store.add(home)
    store.add(trip)
    store.add_link(
        _link(LinkType.TEMPORARILY_OVERRIDES, "trip", "home", expires_at=expires_at(trip, TTL))
    )
    assert validity_at(home, store, T0 + timedelta(days=35), TTL) is Validity.OVERRIDDEN
    assert validity_at(home, store, T0 + timedelta(days=60), TTL) is Validity.CURRENT
    assert validity_at(trip, store, T0 + timedelta(days=60), TTL) is Validity.EXPIRED


def test_archived_and_superseded_status(store: InMemoryStore, make_memory: MakeMemory) -> None:
    a = make_memory("a", status=MemoryStatus.ARCHIVED)
    s = make_memory("s", status=MemoryStatus.SUPERSEDED)
    store.add(a)
    store.add(s)
    assert validity_at(a, store, T0, TTL) is Validity.ARCHIVED
    assert validity_at(s, store, T0, TTL) is Validity.SUPERSEDED
