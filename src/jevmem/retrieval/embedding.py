"""Optional dense-embedding baseline (`pip install -e ".[embeddings]"`).

Exact cosine search with numpy: at per-user memory scales (≤ a few thousand) this is
exact, fast, and avoids an ANN dependency. Embeddings are cached on disk keyed by
(model id, prompt, text hash), so benchmark reruns never re-encode.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from jevmem.retrieval.bm25 import ScoredId

Vector = npt.NDArray[np.float32]

# Task instruction for instruction-tuned embedders (Qwen3-Embedding style). Documents are
# encoded without an instruction, as the model card recommends.
DEFAULT_QUERY_INSTRUCTION = (
    "Instruct: Given a user's request to an assistant, retrieve stored memories about the user "
    "that are relevant to it\nQuery: "
)


class Embedder(Protocol):
    model_id: str

    def encode_queries(self, texts: Sequence[str]) -> Vector: ...

    def encode_documents(self, texts: Sequence[str]) -> Vector: ...


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB NOT NULL)"
        )
        self._lock = threading.Lock()

    @staticmethod
    def key(model_id: str, kind: str, text: str) -> str:
        return hashlib.sha256(f"{model_id}\x00{kind}\x00{text}".encode()).hexdigest()

    def get_many(self, keys: Sequence[str]) -> dict[str, Vector]:
        out: dict[str, Vector] = {}
        with self._lock:
            for start in range(0, len(keys), 500):
                chunk = keys[start : start + 500]
                marks = ",".join("?" * len(chunk))
                for key, blob in self._conn.execute(
                    f"SELECT key, vec FROM emb WHERE key IN ({marks})", chunk
                ):
                    out[key] = np.frombuffer(blob, dtype=np.float32)
        return out

    def put_many(self, items: dict[str, Vector]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO emb VALUES (?, ?)",
                [(k, v.astype(np.float32).tobytes()) for k, v in items.items()],
            )
            self._conn.commit()


class SentenceTransformerEmbedder:
    """sentence-transformers backend with an on-disk cache. Loads lazily on first use."""

    def __init__(
        self,
        model_id: str,
        *,
        cache: EmbeddingCache | None = None,
        query_instruction: str = DEFAULT_QUERY_INSTRUCTION,
        device: str | None = None,
        batch_size: int = 64,
    ) -> None:
        self.model_id = model_id
        self._cache = cache
        self._query_instruction = query_instruction
        self._device = device
        self._batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                import torch
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    'Embeddings need the optional extra: pip install -e ".[embeddings]"'
                ) from exc
            device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
            kwargs: dict[str, Any] = {"device": device}
            if device == "cuda":
                kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
            self._model = SentenceTransformer(self.model_id, **kwargs)
        return self._model

    def _encode(self, texts: Sequence[str], kind: str, prefix: str) -> Vector:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        keys = [EmbeddingCache.key(self.model_id, kind, t) for t in texts]
        found = self._cache.get_many(keys) if self._cache else {}
        missing = [i for i, k in enumerate(keys) if k not in found]
        if missing:
            model = self._load()
            vectors = model.encode(
                [prefix + texts[i] for i in missing],
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).astype(np.float32)
            new = {keys[i]: vectors[j] for j, i in enumerate(missing)}
            found.update(new)
            if self._cache:
                self._cache.put_many(new)
        return np.stack([found[k] for k in keys])

    def encode_queries(self, texts: Sequence[str]) -> Vector:
        return self._encode(texts, "query", self._query_instruction)

    def encode_documents(self, texts: Sequence[str]) -> Vector:
        return self._encode(texts, "document", "")


class EmbeddingIndex:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._ids: list[str] = []
        self._rows: list[Vector] = []
        self._matrix: Vector | None = None

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, memory_id: str, text: str) -> None:
        self.add_many([(memory_id, text)])

    def add_many(self, items: Sequence[tuple[str, str]]) -> None:
        if not items:
            return
        vectors = self.embedder.encode_documents([t for _, t in items])
        self._ids.extend(i for i, _ in items)
        self._rows.extend(vectors)
        self._matrix = None

    def search(self, query: str, limit: int | None = None) -> list[ScoredId]:
        if not self._ids:
            return []
        if self._matrix is None:
            self._matrix = np.stack(self._rows)
        q = self.embedder.encode_queries([query])[0]
        scores = self._matrix @ q
        order = np.lexsort((np.array(self._ids), -scores))
        if limit is not None:
            order = order[:limit]
        return [ScoredId(self._ids[i], float(scores[i])) for i in order]

    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity between two indexed memories."""
        if self._matrix is None:
            self._matrix = np.stack(self._rows)
        ia, ib = self._ids.index(a), self._ids.index(b)
        return float(self._matrix[ia] @ self._matrix[ib])
