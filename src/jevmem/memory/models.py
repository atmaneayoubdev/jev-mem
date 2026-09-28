"""Core memory data model.

Lifecycle state is represented by *links* between memories rather than by mutating or
deleting records: history is never destroyed. A memory's stored `status` only changes
for SUPERSEDED (a durable replacement) and ARCHIVED (an explicit user/system action).
Expiry and temporary overrides are time-dependent, so they are computed against a
supplied `now` (see `jevmem.memory.lineage`) instead of being stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    PROFILE = "profile"
    PREFERENCE = "preference"
    FACT = "fact"
    GOAL = "goal"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    EVENT = "event"
    RELATIONSHIP = "relationship"
    WORK_CONTEXT = "work_context"
    TEMPORARY_STATE = "temporary_state"
    OTHER = "other"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class Durability(StrEnum):
    """How long the content of a memory is expected to stay true."""

    LASTING = "lasting"  # true until something changes it (preferences, residence, employer)
    TEMPORARY = "temporary"  # a current situation expected to end (travel, a sprint)
    EVENT = "event"  # something that happened at a point in time


class Horizon(StrEnum):
    """Expected lifetime of a TEMPORARY memory."""

    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    YEAR = "year"


class LinkType(StrEnum):
    """Directed relation from `source_id` (the later memory) to `target_id` (the earlier one)."""

    SUPERSEDES = "supersedes"
    TEMPORARILY_OVERRIDES = "temporarily_overrides"
    CONFLICTS_WITH = "conflicts_with"
    REINFORCES = "reinforces"
    REFINES = "refines"
    UNCERTAIN_RELATION = "uncertain_relation"


class Memory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_id)
    user_id: str
    session_id: str | None = None
    content: str = Field(min_length=1, max_length=8000)
    normalized_content: str | None = None
    memory_type: MemoryType = MemoryType.OTHER

    created_at: datetime = Field(default_factory=utcnow)
    observed_at: datetime
    # Tie-breaker for memories observed at the same instant (e.g. rounds within a session).
    sequence: int = 0
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_turn_id: str | None = None

    status: MemoryStatus = MemoryStatus.ACTIVE
    durability: Durability | None = None  # None until judged
    horizon: Horizon | None = None
    # Set when lifecycle judgment failed (e.g. judge outage) and must be retried.
    lifecycle_pending: bool = False

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def order_key(self) -> tuple[datetime, int, str]:
        """Total order used by the write pipeline: observation time, then sequence, then id."""
        return (self.observed_at, self.sequence, self.id)


class MemoryLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_id)
    link_type: LinkType
    source_id: str  # later memory
    target_id: str  # earlier memory
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    judge: str  # e.g. "jev:typesafe/jev-1.13-20260917", "qwen:qwen3.8-27b", "heuristic"
    question_schema_version: str | None = None
    policy_version: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    # For TEMPORARILY_OVERRIDES: when the override lapses (the source memory's expiry).
    expires_at: datetime | None = None
