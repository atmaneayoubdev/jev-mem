"""Optional cross-encoder reranking baseline (`pip install -e ".[embeddings]"`)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from jevmem.retrieval.base import CandidateRetriever, MemoryCandidate
from jevmem.retrieval.embedding import EmbeddingCache


class CrossEncoderScorer:
    """Scores (query, memory) pairs as probabilities in [0, 1]. Cached on disk."""

    def __init__(
        self, model_id: str, *, cache: EmbeddingCache | None = None, device: str | None = None
    ) -> None:
        self.model_id = model_id
        self._cache = cache
        self._device = device
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                import torch
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    'Reranking needs the optional extra: pip install -e ".[embeddings]"'
                ) from exc
            device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._model = CrossEncoder(self.model_id, device=device)
        return self._model

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        keys = [EmbeddingCache.key(self.model_id, "rerank", f"{query}\x00{t}") for t in texts]
        found = self._cache.get_many(keys) if self._cache else {}
        missing = [i for i, k in enumerate(keys) if k not in found]
        if missing:
            # Single-label cross-encoders apply their default sigmoid in `predict`, so the
            # output is already a probability in [0, 1].
            probs = np.asarray(
                self._load().predict([(query, texts[i]) for i in missing]), dtype=np.float32
            ).reshape(-1)
            if probs.size and (probs.min() < 0.0 or probs.max() > 1.0):
                raise RuntimeError(f"{self.model_id}: expected probabilities, got raw logits")
            new = {keys[i]: np.array([probs[j]], dtype=np.float32) for j, i in enumerate(missing)}
            found.update(new)
            if self._cache:
                self._cache.put_many(new)
        return [float(found[k][0]) for k in keys]


class RerankRetriever:
    """First-stage retriever → cross-encoder reorder. Scores are kept for threshold baselines."""

    name = "rerank"

    def __init__(
        self, first_stage: CandidateRetriever, scorer: CrossEncoderScorer, *, pool: int = 50
    ) -> None:
        self.first_stage = first_stage
        self.scorer = scorer
        self.pool = pool

    async def retrieve(self, query: str, user_id: str, limit: int) -> list[MemoryCandidate]:
        pool = await self.first_stage.retrieve(query, user_id, max(limit, self.pool))
        if not pool:
            return []
        scores = self.scorer.score(query, [c.memory.content for c in pool])
        ranked = sorted(zip(pool, scores, strict=True), key=lambda cs: (-cs[1], cs[0].memory.id))[
            :limit
        ]
        return [
            MemoryCandidate(memory=c.memory, score=s, rank=i, sources=[*c.sources, self.name])
            for i, (c, s) in enumerate(ranked)
        ]
