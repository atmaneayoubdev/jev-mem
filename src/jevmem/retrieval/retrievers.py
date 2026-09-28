"""Interchangeable candidate generators: recency, BM25, embeddings, all-memory, hybrid."""

from __future__ import annotations

from collections.abc import Sequence

from jevmem.memory.models import MemoryStatus
from jevmem.retrieval.base import CandidateRetriever, MemoryCandidate, MemoryIndex
from jevmem.retrieval.bm25 import ScoredId


def _materialize(
    index: MemoryIndex, scored: Sequence[ScoredId], limit: int, source: str
) -> list[MemoryCandidate]:
    out: list[MemoryCandidate] = []
    for item in scored:
        memory = index.store.get(item.memory_id)
        if memory.status is MemoryStatus.ARCHIVED:
            continue
        out.append(
            MemoryCandidate(memory=memory, score=item.score, rank=len(out), sources=[source])
        )
        if len(out) >= limit:
            break
    return out


class RecencyRetriever:
    name = "recency"

    def __init__(self, index: MemoryIndex) -> None:
        self.index = index

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        order = self.index.user(user_id).order
        scored = [ScoredId(mid, float(len(order) - i)) for i, mid in enumerate(reversed(order))]
        return _materialize(self.index, scored, limit, self.name)


class AllRetriever:
    """Every memory, newest first. Only sensible for small stores."""

    name = "all"

    def __init__(self, index: MemoryIndex) -> None:
        self.index = index

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        order = self.index.user(user_id).order
        return _materialize(
            self.index, [ScoredId(m, 0.0) for m in reversed(order)], limit, self.name
        )


class BM25Retriever:
    name = "bm25"

    def __init__(self, index: MemoryIndex) -> None:
        self.index = index

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        return _materialize(
            self.index, self.index.user(user_id).bm25.search(query), limit, self.name
        )


class EmbeddingRetriever:
    name = "embedding"

    def __init__(self, index: MemoryIndex) -> None:
        if index.embedder is None:
            raise ValueError("EmbeddingRetriever needs a MemoryIndex built with an embedder")
        self.index = index

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        emb = self.index.user(user_id).embedding
        if emb is None:
            return []
        return _materialize(self.index, emb.search(query), limit, self.name)


class HybridRetriever:
    """Union of several retrievers, ordered by reciprocal-rank fusion. Keeps source tags."""

    name = "hybrid"

    def __init__(
        self,
        retrievers: Sequence[CandidateRetriever],
        *,
        per_source_limit: int | None = None,
        rrf_k: int = 60,
    ) -> None:
        if not retrievers:
            raise ValueError("HybridRetriever needs at least one retriever")
        self.retrievers = list(retrievers)
        self.per_source_limit = per_source_limit
        self.rrf_k = rrf_k

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        per_source = self.per_source_limit or limit
        fused: dict[str, float] = {}
        sources: dict[str, list[str]] = {}
        first: dict[str, MemoryCandidate] = {}
        for retriever in self.retrievers:
            for cand in await retriever.retrieve(query, user_id, per_source):
                mid = cand.memory.id
                fused[mid] = fused.get(mid, 0.0) + 1.0 / (self.rrf_k + cand.rank + 1)
                sources.setdefault(mid, []).append(retriever.name)
                first.setdefault(mid, cand)
        ranked = sorted(fused, key=lambda mid: (-fused[mid], mid))[:limit]
        return [
            MemoryCandidate(
                memory=first[mid].memory, score=fused[mid], rank=i, sources=sources[mid]
            )
            for i, mid in enumerate(ranked)
        ]
