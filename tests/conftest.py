from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from jevmem.memory.models import Memory
from jevmem.memory.store import InMemoryStore

T0 = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)

MakeMemory = Callable[..., Memory]


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def make_memory() -> MakeMemory:
    def _make(content: str, days: float = 0.0, *, mid: str | None = None, **kw: object) -> Memory:
        fields: dict[str, object] = {
            "user_id": "u1",
            "content": content,
            "observed_at": T0 + timedelta(days=days),
        }
        if mid is not None:
            fields["id"] = mid
        fields.update(kw)
        return Memory.model_validate(fields)

    return _make
