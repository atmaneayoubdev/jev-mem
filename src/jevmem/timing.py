"""Reproducible latency modelling.

Cached replays make wall-clock time meaningless, so latency metrics are computed from the
originally recorded per-call latencies: concurrent calls under a concurrency limit are
list-scheduled onto `workers` slots in submission order, and the stage takes the makespan.
"""

from __future__ import annotations

import heapq
from collections.abc import Sequence


def makespan(latencies_ms: Sequence[float], workers: int) -> float:
    if not latencies_ms:
        return 0.0
    if workers < 1:
        raise ValueError("workers must be >= 1")
    slots = [0.0] * min(workers, len(latencies_ms))
    heapq.heapify(slots)
    for latency in latencies_ms:
        heapq.heappush(slots, heapq.heappop(slots) + latency)
    return max(slots)
