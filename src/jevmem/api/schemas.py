"""Request/response schemas for the REST API (v1). Field limits are the input-size guards."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from jevmem.memory.models import MemoryType
from jevmem.memory.service import Mode

USER_ID = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:@/-]+$")


class ChatRequest(BaseModel):
    user_id: str = USER_ID
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=200)
    mode: Mode | None = None
    now: datetime | None = Field(default=None, description="Override the current time (demos).")
    extract: bool = True


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    extracted: list[dict[str, Any]]
    extraction_error: str | None = None
    latency_ms: dict[str, float]
    memory_debug: dict[str, Any] | None = None


class MemoryCreate(BaseModel):
    user_id: str = USER_ID
    content: str = Field(min_length=1, max_length=4000)
    memory_type: MemoryType = MemoryType.OTHER
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(BaseModel):
    user_id: str = USER_ID
    query: str = Field(min_length=1, max_length=4000)
    mode: Mode | None = None
    now: datetime | None = None


class CompareRequest(BaseModel):
    user_id: str = USER_ID
    query: str = Field(min_length=1, max_length=4000)
    modes: list[Mode] | None = None
    now: datetime | None = None


class DemoRequest(BaseModel):
    user_id: str = Field(
        default="alex", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:@/-]+$"
    )


class BenchmarkRunRequest(BaseModel):
    split: str = Field(default="dev", pattern=r"^(dev|calib|test)$")
    systems: list[str] | None = None
    limit: int | None = Field(default=22, ge=1, le=1000)
    n_background: int = Field(default=20, ge=0, le=1000)
