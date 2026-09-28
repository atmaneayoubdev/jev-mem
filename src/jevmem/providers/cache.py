"""Content-addressed response cache (SQLite).

Every model call is keyed by a hash of (provider, full request payload). The payload
includes the model id, so pinning a dated model id (e.g. `typesafe/jev-1.13-20260917`)
makes cached entries immutable. Each entry also stores the model id the server reported
and the originally measured latency, so replays reproduce latency metrics exactly.

Modes:
- ``off``: never read or write.
- ``readwrite``: read on hit, call and store on miss.
- ``replay``: read only; a miss raises `CacheMissError` (offline reproduction).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CacheMode = Literal["off", "readwrite", "replay"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(provider: str, payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json({"provider": provider, "payload": payload}).encode()
    ).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    response: dict[str, Any]
    resolved_model: str | None
    latency_ms: float


class ResponseCache:
    def __init__(self, path: Path | None, mode: CacheMode = "readwrite") -> None:
        self.mode: CacheMode = mode if path is not None else "off"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if path is not None and self.mode != "off":
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS responses (
                    key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    requested_model TEXT,
                    resolved_model TEXT,
                    latency_ms REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    response TEXT NOT NULL
                )"""
            )
            self._conn.commit()

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def get(self, key: str) -> CachedResponse | None:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT response, resolved_model, latency_ms FROM responses WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return CachedResponse(json.loads(row[0]), row[1], float(row[2]))

    def put(
        self,
        key: str,
        *,
        provider: str,
        requested_model: str | None,
        resolved_model: str | None,
        response: Mapping[str, Any],
        latency_ms: float,
    ) -> None:
        if self._conn is None or self.mode != "readwrite":
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    provider,
                    requested_model,
                    resolved_model,
                    latency_ms,
                    datetime.now(UTC).isoformat(),
                    canonical_json(response),
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
            self._conn = None
