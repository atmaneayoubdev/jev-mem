"""SQL-backed MemoryStore plus conversation-turn storage.

All queries go through the ORM (parameterised). The store satisfies the same
`MemoryStore` protocol as `InMemoryStore`, so the lifecycle and recall pipelines run
unchanged against it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from jevmem.database.models import LinkRow, MemoryRow, TurnRow
from jevmem.memory.models import (
    Durability,
    Horizon,
    LinkType,
    Memory,
    MemoryLink,
    MemoryStatus,
    MemoryType,
)
from jevmem.memory.store import MemoryNotFoundError


def _utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; everything in JevMem is UTC-aware."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_row(m: Memory) -> MemoryRow:
    return MemoryRow(
        id=m.id,
        user_id=m.user_id,
        session_id=m.session_id,
        content=m.content,
        normalized_content=m.normalized_content,
        memory_type=m.memory_type.value,
        created_at=m.created_at,
        observed_at=m.observed_at,
        sequence=m.sequence,
        valid_from=m.valid_from,
        valid_until=m.valid_until,
        source_turn_id=m.source_turn_id,
        status=m.status.value,
        durability=m.durability.value if m.durability else None,
        horizon=m.horizon.value if m.horizon else None,
        lifecycle_pending=m.lifecycle_pending,
        instruction_like=m.instruction_like,
        confidence=m.confidence,
        tags=list(m.tags),
        extra=dict(m.metadata),
    )


def _from_row(r: MemoryRow) -> Memory:
    return Memory(
        id=r.id,
        user_id=r.user_id,
        session_id=r.session_id,
        content=r.content,
        normalized_content=r.normalized_content,
        memory_type=MemoryType(r.memory_type),
        created_at=_utc(r.created_at) or datetime.now(UTC),
        observed_at=_utc(r.observed_at) or datetime.now(UTC),
        sequence=r.sequence,
        valid_from=_utc(r.valid_from),
        valid_until=_utc(r.valid_until),
        source_turn_id=r.source_turn_id,
        status=MemoryStatus(r.status),
        durability=Durability(r.durability) if r.durability else None,
        horizon=Horizon(r.horizon) if r.horizon else None,
        lifecycle_pending=r.lifecycle_pending,
        instruction_like=r.instruction_like,
        confidence=r.confidence,
        tags=list(r.tags or []),
        metadata=dict(r.extra or {}),
    )


def _link_from_row(r: LinkRow) -> MemoryLink:
    return MemoryLink(
        id=r.id,
        link_type=LinkType(r.link_type),
        source_id=r.source_id,
        target_id=r.target_id,
        probabilities=dict(r.probabilities or {}),
        confidence=r.confidence,
        judge=r.judge,
        question_schema_version=r.question_schema_version,
        policy_version=r.policy_version,
        created_at=_utc(r.created_at) or datetime.now(UTC),
        expires_at=_utc(r.expires_at),
    )


class SqlMemoryStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    # --- MemoryStore protocol ---------------------------------------------------------

    def add(self, memory: Memory) -> None:
        with self._sessions.begin() as s:
            if s.get(MemoryRow, memory.id) is not None:
                raise ValueError(f"memory {memory.id} already exists")
            s.add(_to_row(memory))

    def get(self, memory_id: str) -> Memory:
        with self._sessions() as s:
            row = s.get(MemoryRow, memory_id)
            if row is None:
                raise MemoryNotFoundError(memory_id)
            return _from_row(row)

    def update(self, memory: Memory) -> None:
        with self._sessions.begin() as s:
            if s.get(MemoryRow, memory.id) is None:
                raise MemoryNotFoundError(memory.id)
            s.merge(_to_row(memory))

    def list_memories(
        self, user_id: str, statuses: Iterable[MemoryStatus] | None = None
    ) -> list[Memory]:
        stmt = select(MemoryRow).where(MemoryRow.user_id == user_id)
        if statuses is not None:
            stmt = stmt.where(MemoryRow.status.in_([st.value for st in statuses]))
        stmt = stmt.order_by(MemoryRow.observed_at, MemoryRow.sequence, MemoryRow.id)
        with self._sessions() as s:
            return [_from_row(r) for r in s.scalars(stmt)]

    def add_link(self, link: MemoryLink) -> None:
        with self._sessions.begin() as s:
            for endpoint in (link.source_id, link.target_id):
                if s.get(MemoryRow, endpoint) is None:
                    raise MemoryNotFoundError(endpoint)
            s.add(
                LinkRow(
                    id=link.id,
                    link_type=link.link_type.value,
                    source_id=link.source_id,
                    target_id=link.target_id,
                    probabilities=dict(link.probabilities),
                    confidence=link.confidence,
                    judge=link.judge,
                    question_schema_version=link.question_schema_version,
                    policy_version=link.policy_version,
                    created_at=link.created_at,
                    expires_at=link.expires_at,
                )
            )

    def links_from(
        self, memory_id: str, types: Iterable[LinkType] | None = None
    ) -> list[MemoryLink]:
        return self._links(LinkRow.source_id == memory_id, types)

    def links_to(self, memory_id: str, types: Iterable[LinkType] | None = None) -> list[MemoryLink]:
        return self._links(LinkRow.target_id == memory_id, types)

    def _links(self, condition: Any, types: Iterable[LinkType] | None) -> list[MemoryLink]:
        stmt = select(LinkRow).where(condition).order_by(LinkRow.created_at, LinkRow.id)
        if types is not None:
            stmt = stmt.where(LinkRow.link_type.in_([t.value for t in types]))
        with self._sessions() as s:
            return [_link_from_row(r) for r in s.scalars(stmt)]

    # --- extras for the API ---------------------------------------------------------------

    def users(self) -> list[str]:
        with self._sessions() as s:
            return sorted(s.scalars(select(MemoryRow.user_id).distinct()))

    def all_links(self, user_id: str) -> list[MemoryLink]:
        ids = select(MemoryRow.id).where(MemoryRow.user_id == user_id)
        stmt = select(LinkRow).where(or_(LinkRow.source_id.in_(ids), LinkRow.target_id.in_(ids)))
        with self._sessions() as s:
            return [_link_from_row(r) for r in s.scalars(stmt.order_by(LinkRow.created_at))]

    def delete_user(self, user_id: str) -> int:
        """Hard reset for demo data only (`jevmem demo reset`). Normal deletes archive."""
        with self._sessions.begin() as s:
            ids = list(s.scalars(select(MemoryRow.id).where(MemoryRow.user_id == user_id)))
            if ids:
                s.execute(
                    delete(LinkRow).where(
                        or_(LinkRow.source_id.in_(ids), LinkRow.target_id.in_(ids))
                    )
                )
                s.execute(delete(MemoryRow).where(MemoryRow.id.in_(ids)))
            s.execute(delete(TurnRow).where(TurnRow.user_id == user_id))
            return len(ids)


class TurnStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        *,
        retrieval_mode: str | None = None,
        debug: dict[str, Any] | None = None,
    ) -> str:
        turn_id = uuid4().hex
        with self._sessions.begin() as s:
            s.add(
                TurnRow(
                    id=turn_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    created_at=datetime.now(UTC),
                    retrieval_mode=retrieval_mode,
                    debug=debug,
                )
            )
        return turn_id

    def history(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        stmt = (
            select(TurnRow)
            .where(TurnRow.conversation_id == conversation_id)
            .order_by(TurnRow.created_at.desc())
            .limit(limit)
        )
        with self._sessions() as s:
            rows = list(s.scalars(stmt))
        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "created_at": (_utc(r.created_at) or datetime.now(UTC)).isoformat(),
                "retrieval_mode": r.retrieval_mode,
                "debug": r.debug,
            }
            for r in reversed(rows)
        ]
