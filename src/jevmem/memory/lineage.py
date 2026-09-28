"""Lineage traversal and time-dependent validity.

All date/time reasoning in JevMem happens here, in Python, against an explicit `now`.
Jev reads dates as text and cannot order them reliably, so it is never asked to.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum

from jevmem.memory.models import Durability, Horizon, LinkType, Memory, MemoryStatus
from jevmem.memory.store import MemoryStore

# Fallback when a TEMPORARY memory has no judged horizon.
_DEFAULT_HORIZON = Horizon.WEEKS


class Validity(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    OVERRIDDEN = "overridden"  # a temporary memory currently overrides it
    ARCHIVED = "archived"

    @property
    def is_current(self) -> bool:
        return self is Validity.CURRENT


def expires_at(memory: Memory, ttl: Mapping[Horizon, timedelta]) -> datetime | None:
    """Explicit `valid_until` wins; TEMPORARY memories otherwise expire after their TTL."""
    if memory.valid_until is not None:
        return memory.valid_until
    if memory.durability is Durability.TEMPORARY:
        return memory.observed_at + ttl[memory.horizon or _DEFAULT_HORIZON]
    return None


def validity_at(
    memory: Memory,
    store: MemoryStore,
    now: datetime,
    ttl: Mapping[Horizon, timedelta],
) -> Validity:
    if memory.status is MemoryStatus.ARCHIVED:
        return Validity.ARCHIVED
    if memory.status is MemoryStatus.SUPERSEDED:
        return Validity.SUPERSEDED
    expiry = expires_at(memory, ttl)
    if expiry is not None and expiry <= now:
        return Validity.EXPIRED
    for link in store.links_to(memory.id, [LinkType.TEMPORARILY_OVERRIDES]):
        overrider = store.get(link.source_id)
        # The override lasts as long as the overriding memory is valid, computed with the TTL
        # table in force now (not the one at write time), so TTLs can be calibrated offline.
        lapse = expires_at(overrider, ttl)
        if overrider.observed_at <= now and (lapse is None or lapse > now):
            return Validity.OVERRIDDEN
    return Validity.CURRENT


def successors(store: MemoryStore, memory_id: str) -> list[Memory]:
    """Memories that directly supersede `memory_id`, oldest first."""
    found = [store.get(link.source_id) for link in store.links_to(memory_id, [LinkType.SUPERSEDES])]
    return sorted(found, key=lambda m: m.order_key)


def predecessors(store: MemoryStore, memory_id: str) -> list[Memory]:
    """Memories directly superseded by `memory_id`, oldest first."""
    found = [
        store.get(link.target_id) for link in store.links_from(memory_id, [LinkType.SUPERSEDES])
    ]
    return sorted(found, key=lambda m: m.order_key)


def supersession_chain(store: MemoryStore, memory_id: str) -> list[Memory]:
    """Every memory connected to `memory_id` by SUPERSEDES edges (either direction), in order."""
    return _component(store, memory_id, LinkType.SUPERSEDES)


def chain_head(store: MemoryStore, memory_id: str) -> Memory:
    """The newest non-superseded member of the chain containing `memory_id`."""
    chain = supersession_chain(store, memory_id)
    heads = [m for m in chain if m.status is not MemoryStatus.SUPERSEDED]
    return (heads or chain)[-1]


def reinforce_cluster(store: MemoryStore, memory_id: str) -> list[Memory]:
    """Memories that restate the same fact (REINFORCES component), in order."""
    return _component(store, memory_id, LinkType.REINFORCES)


def conflict_partners(store: MemoryStore, memory_id: str) -> list[Memory]:
    ids = {link.target_id for link in store.links_from(memory_id, [LinkType.CONFLICTS_WITH])}
    ids |= {link.source_id for link in store.links_to(memory_id, [LinkType.CONFLICTS_WITH])}
    return sorted((store.get(i) for i in ids), key=lambda m: m.order_key)


def _component(store: MemoryStore, memory_id: str, link_type: LinkType) -> list[Memory]:
    seen = {memory_id}
    queue = deque([memory_id])
    while queue:
        current = queue.popleft()
        neighbours = [link.target_id for link in store.links_from(current, [link_type])]
        neighbours += [link.source_id for link in store.links_to(current, [link_type])]
        for n in neighbours:
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return sorted((store.get(i) for i in seen), key=lambda m: m.order_key)
