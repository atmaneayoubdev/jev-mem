"""Incremental Okapi BM25 over an inverted index.

Documents are added one at a time as memories are written, so at any moment the index
(and its IDF statistics) reflects exactly the memories that exist, which keeps write-time
neighbour search independent of future memories.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import NamedTuple

from jevmem.retrieval.text import tokenize


class ScoredId(NamedTuple):
    memory_id: str
    score: float


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._postings: dict[str, dict[str, int]] = defaultdict(dict)  # term -> {doc: tf}
        self._lengths: dict[str, int] = {}
        self._total_length = 0

    def __len__(self) -> int:
        return len(self._lengths)

    def add(self, memory_id: str, text: str) -> None:
        if memory_id in self._lengths:
            raise ValueError(f"{memory_id} already indexed")
        terms = tokenize(text)
        for term, tf in Counter(terms).items():
            self._postings[term][memory_id] = tf
        self._lengths[memory_id] = len(terms)
        self._total_length += len(terms)

    def idf(self, term: str) -> float:
        n = len(self._lengths)
        df = len(self._postings.get(term, {}))
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, limit: int | None = None) -> list[ScoredId]:
        """Documents sharing at least one query term, best first; ties broken by id."""
        if not self._lengths:
            return []
        avg_len = self._total_length / len(self._lengths) or 1.0
        scores: dict[str, float] = defaultdict(float)
        for term in set(tokenize(query)):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for doc, tf in postings.items():
                norm = self.k1 * (1 - self.b + self.b * self._lengths[doc] / avg_len)
                scores[doc] += idf * tf * (self.k1 + 1) / (tf + norm)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [ScoredId(d, s) for d, s in (ranked if limit is None else ranked[:limit])]
