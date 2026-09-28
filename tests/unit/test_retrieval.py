from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from jevmem.memory.models import LinkType, MemoryLink, MemoryStatus
from jevmem.memory.store import InMemoryStore
from jevmem.retrieval.base import MemoryIndex
from jevmem.retrieval.bm25 import BM25Index
from jevmem.retrieval.embedding import EmbeddingCache, EmbeddingIndex, Vector
from jevmem.retrieval.expansion import expand_candidates
from jevmem.retrieval.retrievers import (
    AllRetriever,
    BM25Retriever,
    EmbeddingRetriever,
    HybridRetriever,
    RecencyRetriever,
)
from jevmem.retrieval.text import stem, tokenize
from tests.conftest import MakeMemory


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests."""

    model_id = "hash-test"

    def _vec(self, text: str) -> Vector:
        v = np.zeros(64, dtype=np.float32)
        for tok in tokenize(text):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 64] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_queries(self, texts: Sequence[str]) -> Vector:
        return np.stack([self._vec(t) for t in texts])

    def encode_documents(self, texts: Sequence[str]) -> Vector:
        return np.stack([self._vec(t) for t in texts])


def test_tokenize_and_stem() -> None:
    assert tokenize("I like window seats!") == ["like", "window", "seat"]
    assert stem("hotels") == "hotel"
    assert stem("studies") == "study"
    assert stem("booking") == "book"
    assert stem("bus") == "bus"


def test_bm25_ranks_by_term_overlap_and_idf() -> None:
    idx = BM25Index()
    idx.add("a", "preferred cloud provider is AWS")
    idx.add("b", "migrated everything to Azure cloud")
    idx.add("c", "likes window seats on flights")
    ranked = idx.search("which cloud provider")
    assert [r.memory_id for r in ranked] == ["a", "b"]
    assert idx.search("nothing matches here") == []
    assert idx.idf("cloud") < idx.idf("window")  # rarer term, higher idf
    with pytest.raises(ValueError, match="already indexed"):
        idx.add("a", "dup")


@pytest.fixture
def indexed(store: InMemoryStore, make_memory: MakeMemory) -> MemoryIndex:
    index = MemoryIndex(store, HashEmbedder())
    memories = [
        make_memory("My preferred cloud provider is AWS.", 0, mid="aws"),
        make_memory("I like window seats on flights.", 10, mid="seat"),
        make_memory("We moved everything to Azure.", 20, mid="azure"),
        make_memory("My sister lives in Lisbon.", 30, mid="sister"),
    ]
    for m in memories:
        store.add(m)
    index.add_many(memories)
    return index


async def test_recency_and_all(indexed: MemoryIndex) -> None:
    assert [c.memory.id for c in await RecencyRetriever(indexed).retrieve("x", "u1", 2)] == [
        "sister",
        "azure",
    ]
    assert len(await AllRetriever(indexed).retrieve("x", "u1", 100)) == 4


async def test_archived_memories_are_never_candidates(
    indexed: MemoryIndex, store: InMemoryStore
) -> None:
    m = store.get("aws")
    m.status = MemoryStatus.ARCHIVED
    store.update(m)
    ids = [c.memory.id for c in await AllRetriever(indexed).retrieve("x", "u1", 100)]
    assert "aws" not in ids


async def test_bm25_and_embedding_retrievers(indexed: MemoryIndex) -> None:
    bm25 = await BM25Retriever(indexed).retrieve("preferred cloud", "u1", 5)
    assert bm25[0].memory.id == "aws"
    assert bm25[0].sources == ["bm25"]
    emb = await EmbeddingRetriever(indexed).retrieve("window seats", "u1", 2)
    assert emb[0].memory.id == "seat"


async def test_hybrid_unions_sources_with_rrf(indexed: MemoryIndex) -> None:
    hybrid = HybridRetriever(
        [BM25Retriever(indexed), RecencyRetriever(indexed)], per_source_limit=2
    )
    result = await hybrid.retrieve("preferred cloud provider", "u1", 10)
    by_id = {c.memory.id: c for c in result}
    assert by_id["aws"].sources == ["bm25"]
    assert by_id["sister"].sources == ["recency"]
    assert [c.rank for c in result] == list(range(len(result)))
    assert len(await hybrid.retrieve("preferred cloud provider", "u1", 1)) == 1


def test_embedding_cache_roundtrip(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "e.sqlite3")
    key = EmbeddingCache.key("m", "document", "hello")
    cache.put_many({key: np.array([0.5, 0.25], dtype=np.float32)})
    assert cache.get_many([key, "missing"])[key].tolist() == [0.5, 0.25]


def test_embedding_index_similarity() -> None:
    idx = EmbeddingIndex(HashEmbedder())
    idx.add_many([("a", "window seat"), ("b", "window seats"), ("c", "cloud provider")])
    assert idx.similarity("a", "b") == pytest.approx(1.0)
    assert idx.similarity("a", "c") < 0.5


def _link(kind: LinkType, source: str, target: str) -> MemoryLink:
    return MemoryLink(link_type=kind, source_id=source, target_id=target, judge="test")


async def test_expansion_follows_links(
    indexed: MemoryIndex, store: InMemoryStore, make_memory: MakeMemory
) -> None:
    store.add_link(_link(LinkType.SUPERSEDES, "azure", "aws"))
    m = store.get("aws")
    m.status = MemoryStatus.SUPERSEDED
    store.update(m)
    store.add(make_memory("I'm vegetarian.", 5, mid="veg"))
    store.add(make_memory("I eat steak often.", 6, mid="steak"))
    store.add_link(_link(LinkType.CONFLICTS_WITH, "steak", "veg"))

    aws_only = await BM25Retriever(indexed).retrieve("preferred cloud provider", "u1", 1)
    expanded = expand_candidates(aws_only, store, intent="current")
    assert [(c.memory.id, c.sources) for c in expanded] == [
        ("aws", ["bm25"]),
        ("azure", ["link:successor"]),
    ]

    azure_only = await BM25Retriever(indexed).retrieve("Azure", "u1", 1)
    assert [c.memory.id for c in expand_candidates(azure_only, store, intent="current")] == [
        "azure"
    ]
    hist = expand_candidates(azure_only, store, intent="historical")
    assert [(c.memory.id, c.sources) for c in hist] == [
        ("azure", ["bm25"]),
        ("aws", ["link:predecessor"]),
    ]

    veg = [c for c in await AllRetriever(indexed).retrieve("x", "u1", 100) if c.memory.id == "veg"]
    assert veg == []  # not indexed (added to the store only); expansion still reaches partners
    from jevmem.retrieval.base import MemoryCandidate

    seed = [MemoryCandidate(memory=store.get("veg"), score=1.0, rank=0, sources=["bm25"])]
    assert [c.memory.id for c in expand_candidates(seed, store, "current")] == ["veg", "steak"]
    assert expand_candidates(seed, store, "current", max_added=0) == seed
