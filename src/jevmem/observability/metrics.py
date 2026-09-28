"""In-process service metrics (counters + latency summaries), exposed at /metrics/summary."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._latencies: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, value_ms: float) -> None:
        with self._lock:
            samples = self._latencies[name]
            samples.append(value_ms)
            if len(samples) > 5000:  # bounded memory: keep the most recent samples
                del samples[: len(samples) - 5000]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            latencies = {}
            for name, samples in self._latencies.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                latencies[name] = {
                    "count": len(ordered),
                    "mean": round(sum(ordered) / len(ordered), 1),
                    "p50": round(ordered[len(ordered) // 2], 1),
                    "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
                }
            return {"counters": dict(self._counters), "latency_ms": latencies}
