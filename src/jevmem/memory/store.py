"""Memory storage.

`MemoryStore` is the persistence boundary. M1 ships an in-memory implementation used by
the benchmark (one isolated store per case); a SQLAlchemy implementation arrives with the
API in M2 behind the same protocol.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from jevmem.memory.models import LinkType, Memory, MemoryLink, MemoryStatus


class MemoryNotFoundError(KeyError):
    pass


class MemoryStore(Protocol):
    def add(self, memory: Memory) -> None: ...
    def get(self, memory_id: str) -> Memory: ...
    def update(self, memory: Memory) -> None: ...
    def list_memories(
        self, user_id: str, statuses: Iterable[MemoryStatus] | None = None
    ) -> list[Memory]: ...
    def add_link(self, link: MemoryLink) -> None: ...
    def links_from(
        self, memory_id: str, types: Iterable[LinkType] | None = None
    ) -> list[MemoryLink]: ...
    def links_to(
        self, memory_id: str, types: Iterable[LinkType] | None = None
    ) -> list[MemoryLink]: ...


class InMemoryStore:
    """Dict-backed store. Returns copies so callers cannot mutate stored state implicitly."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}
        self._by_user: dict[str, list[str]] = defaultdict(list)
        self._links_from: dict[str, list[MemoryLink]] = defaultdict(list)
        self._links_to: dict[str, list[MemoryLink]] = defaultdict(list)

    def add(self, memory: Memory) -> None:
        if memory.id in self._memories:
            raise ValueError(f"memory {memory.id} already exists")
        self._memories[memory.id] = memory.model_copy(deep=True)
        self._by_user[memory.user_id].append(memory.id)

    def get(self, memory_id: str) -> Memory:
        try:
            return self._memories[memory_id].model_copy(deep=True)
        except KeyError:
            raise MemoryNotFoundError(memory_id) from None

    def update(self, memory: Memory) -> None:
        if memory.id not in self._memories:
            raise MemoryNotFoundError(memory.id)
        self._memories[memory.id] = memory.model_copy(deep=True)

    def list_memories(
        self, user_id: str, statuses: Iterable[MemoryStatus] | None = None
    ) -> list[Memory]:
        wanted = set(statuses) if statuses is not None else None
        out = [self._memories[i] for i in self._by_user.get(user_id, [])]
        if wanted is not None:
            out = [m for m in out if m.status in wanted]
        return [m.model_copy(deep=True) for m in sorted(out, key=lambda m: m.order_key)]

    def add_link(self, link: MemoryLink) -> None:
        for endpoint in (link.source_id, link.target_id):
            if endpoint not in self._memories:
                raise MemoryNotFoundError(endpoint)
        self._links_from[link.source_id].append(link)
        self._links_to[link.target_id].append(link)

    def links_from(
        self, memory_id: str, types: Iterable[LinkType] | None = None
    ) -> list[MemoryLink]:
        return _filter(self._links_from.get(memory_id, []), types)

    def links_to(self, memory_id: str, types: Iterable[LinkType] | None = None) -> list[MemoryLink]:
        return _filter(self._links_to.get(memory_id, []), types)


def _filter(links: list[MemoryLink], types: Iterable[LinkType] | None) -> list[MemoryLink]:
    if types is None:
        return list(links)
    wanted = set(types)
    return [link for link in links if link.link_type in wanted]
