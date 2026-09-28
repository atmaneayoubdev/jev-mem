"""Token-budgeted memory context assembly, shared by every retrieval system.

All systems (baselines and JevMem) render through this builder with the same budget and
format, so benchmark differences come from *which* memories are selected, not from
presentation. Units are filled greedily by priority; a unit that does not fit is
skipped and smaller ones may still fit. Provenance is kept per item for debugging and
evaluation; the rendered text stays concise.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from jevmem.memory.lineage import conflict_partners, reinforce_cluster, supersession_chain
from jevmem.memory.models import Memory, MemoryStatus
from jevmem.memory.store import MemoryStore

TokenCounter = Callable[[str], int]

HEADER = "Memories about the user (dates show when each was recorded):"


def approx_tokens(text: str) -> int:
    """~4 characters per token. Reported Qwen token counts come from the endpoint instead."""
    return max(1, math.ceil(len(text) / 4))


class ContextEntry(BaseModel):
    """A memory proposed for injection, with its priority and presentation hints."""

    memory: Memory
    priority: float
    label: str  # e.g. "use", "conflict", "rank"
    annotations: list[str] = Field(default_factory=list)
    conflict: bool = False


class ContextItem(BaseModel):
    memory_ids: list[str]
    text: str
    tokens: int
    labels: list[str]
    provenance: list[dict[str, object]]


class ContextResult(BaseModel):
    text: str
    items: list[ContextItem]
    tokens: int
    budget: int
    skipped_for_budget: list[str] = Field(default_factory=list)
    deduplicated: list[str] = Field(default_factory=list)

    @property
    def memory_ids(self) -> list[str]:
        return [mid for item in self.items for mid in item.memory_ids]


def _date(m: Memory) -> str:
    return m.observed_at.date().isoformat()


def _line(m: Memory, annotations: Sequence[str] = ()) -> str:
    note = f" ({'; '.join(annotations)})" if annotations else ""
    return f"[{_date(m)}] {m.content}{note}"


class ContextBuilder:
    def __init__(
        self, store: MemoryStore, budget: int, counter: TokenCounter = approx_tokens
    ) -> None:
        self.store = store
        self.budget = budget
        self.counter = counter

    def build(self, entries: Sequence[ContextEntry], now: datetime | None = None) -> ContextResult:
        ordered = sorted(entries, key=lambda e: (-e.priority, e.memory.order_key))
        by_id = {e.memory.id: e for e in ordered}

        # 1) duplicates: keep only the newest selected member of each REINFORCES cluster
        deduplicated: list[str] = []
        kept: list[ContextEntry] = []
        for entry in ordered:
            cluster = [
                m.id for m in reinforce_cluster(self.store, entry.memory.id) if m.id in by_id
            ]
            if len(cluster) > 1 and entry.memory.id != max(
                cluster, key=lambda i: by_id[i].memory.order_key
            ):
                deduplicated.append(entry.memory.id)
                continue
            kept.append(entry)

        # 2) group into units: supersession chains -> one timeline; conflicts -> one unit
        units: list[list[ContextEntry]] = []
        placed: set[str] = set()
        kept_ids = {e.memory.id for e in kept}
        for entry in kept:
            if entry.memory.id in placed:
                continue
            chain = [
                m.id for m in supersession_chain(self.store, entry.memory.id) if m.id in kept_ids
            ]
            group_ids = chain if len(chain) > 1 else [entry.memory.id]
            if entry.conflict:
                partners = {p.id for p in conflict_partners(self.store, entry.memory.id)}
                for other in kept:
                    oid = other.memory.id
                    if (
                        other.conflict
                        and oid in partners
                        and oid not in placed
                        and oid not in group_ids
                    ):
                        group_ids.append(oid)
            unit = sorted((by_id[i] for i in group_ids), key=lambda e: e.memory.order_key)
            placed.update(group_ids)
            units.append(unit)

        # 3) greedy fill under the budget
        items: list[ContextItem] = []
        skipped: list[str] = []
        used = self.counter(HEADER)
        for unit in units:
            text = self._render(unit)
            tokens = self.counter(text)
            if used + tokens > self.budget:
                skipped.extend(e.memory.id for e in unit)
                continue
            used += tokens
            items.append(
                ContextItem(
                    memory_ids=[e.memory.id for e in unit],
                    text=text,
                    tokens=tokens,
                    labels=[e.label for e in unit],
                    provenance=[
                        {
                            "memory_id": e.memory.id,
                            "observed_at": e.memory.observed_at.isoformat(),
                            "status": e.memory.status.value,
                            "label": e.label,
                            "priority": round(e.priority, 4),
                            "annotations": e.annotations,
                        }
                        for e in unit
                    ],
                )
            )
        text = "\n".join([HEADER, *(i.text for i in items)]) if items else ""
        return ContextResult(
            text=text,
            items=items,
            tokens=used if items else 0,
            budget=self.budget,
            skipped_for_budget=skipped,
            deduplicated=deduplicated,
        )

    @staticmethod
    def _render(unit: Sequence[ContextEntry]) -> str:
        if len(unit) == 1:
            return "- " + _line(unit[0].memory, unit[0].annotations)
        if all(e.conflict for e in unit):
            return "- Conflicting memories (unresolved): " + " | ".join(
                _line(e.memory) for e in unit
            )
        # supersession chain, oldest to newest
        parts = [
            _line(
                e.memory, ["replaced" if e.memory.status is MemoryStatus.SUPERSEDED else "current"]
            )
            for e in unit
        ]
        return "- Timeline (older → newer): " + " → ".join(parts)
