"""SQLAlchemy 2.x ORM models. Portable across SQLite (default) and PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MemoryRow(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    session_id: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_turn_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    durability: Mapped[str | None] = mapped_column(String(16))
    horizon: Mapped[str | None] = mapped_column(String(16))
    lifecycle_pending: Mapped[bool] = mapped_column(default=False)
    instruction_like: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    __table_args__ = (Index("ix_memories_user_order", "user_id", "observed_at", "sequence"),)


class LinkRow(Base):
    __tablename__ = "memory_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    link_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    probabilities: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    judge: Mapped[str] = mapped_column(String(128))
    question_schema_version: Mapped[str | None] = mapped_column(String(32))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TurnRow(Base):
    """Conversation turns. Assistant turns keep the recall debug payload for the inspector."""

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieval_mode: Mapped[str | None] = mapped_column(String(32))
    debug: Mapped[dict[str, Any] | None] = mapped_column(JSON)
