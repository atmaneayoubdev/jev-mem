"""Candidate retrieval interface and the per-user search index it reads from."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from jevmem.memory.models import Memory
from jevmem.memory.store import MemoryStore
from jevmem.retrieval.bm25 import BM25Index
from jevmem.retrieval.embedding import Embedder, EmbeddingIndex


class MemoryCandidate(BaseModel):
    memory: Memory
    score: float
    rank: int
    sources: list[str] = Field(default_factory=list)


class CandidateRetriever(Protocol):
    name: str

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]: ...


@dataclass
class UserIndex:
    bm25: BM25Index = field(default_factory=BM25Index)
    embedding: EmbeddingIndex | None = None
    order: list[str] = field(default_factory=list)  # memory ids in write order


class MemoryIndex:
    """Search structures kept in sync with the store by the write pipeline.

    Memories must be added in write (observation) order; each user's index then contains
    exactly the memories that existed at any point of the write sequence.
    """

    def __init__(self, store: MemoryStore, embedder: Embedder | None = None) -> None:
        self.store = store
        self.embedder = embedder
        self._users: dict[str, UserIndex] = {}

    def user(self, user_id: str) -> UserIndex:
        if user_id not in self._users:
            embedding = EmbeddingIndex(self.embedder) if self.embedder is not None else None
            self._users[user_id] = UserIndex(embedding=embedding)
        return self._users[user_id]

    def add(self, memory: Memory) -> None:
        self.add_many([memory])

    def add_many(self, memories: Sequence[Memory]) -> None:
        for user_id in dict.fromkeys(m.user_id for m in memories):
            batch = [m for m in memories if m.user_id == user_id]
            index = self.user(user_id)
            for m in batch:
                index.bm25.add(m.id, m.content)
                index.order.append(m.id)
            if index.embedding is not None:
                index.embedding.add_many([(m.id, m.content) for m in batch])
