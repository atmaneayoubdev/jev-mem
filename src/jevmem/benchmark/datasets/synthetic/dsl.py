"""A small, explicit DSL for template families.

A *family* is one scenario template with slots; *instances* are seeded slot fillings.
Splits are assigned per family (the module a family lives in decides its split), so no
template wording is shared between dev, calib, and test.

Times are day offsets from a per-instance random start date. `now` is the query's day.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from jevmem.benchmark.datasets.schema import (
    AnswerMode,
    Case,
    CaseMemory,
    ExpectedAnswer,
    GoldRelation,
    Label,
    Relation,
    Split,
)

DATASET = "synthetic-v1"
EPOCH = datetime(2025, 1, 6, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class M:
    id: str
    text: str
    day: float
    label: Label
    durability: str | None = None


@dataclass(frozen=True)
class A:
    aliases: Sequence[str] = ()
    forbidden: Sequence[str] = ()
    mode: AnswerMode = "value"


@dataclass(frozen=True)
class Family:
    id: str
    category: str
    memories: Sequence[M]
    query: str
    query_day: float
    intent: str
    answer: A
    slots: Mapping[str, Sequence[str]] = field(default_factory=dict)
    distinct: Sequence[Sequence[str]] = ()  # groups of slots that must take different values
    relations: Sequence[tuple[str, str, Relation]] = ()
    background: bool = True

    def instances(self, n: int, split: Split, seed: int) -> list[Case]:
        rng = random.Random(f"{seed}:{self.id}")
        cases: list[Case] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        attempts = 0
        while len(cases) < n:
            attempts += 1
            if attempts > 500:
                raise ValueError(f"{self.id}: cannot draw {n} distinct slot fillings")
            values = self._draw(rng)
            key = tuple(sorted(values.items()))
            if key in seen:
                continue
            seen.add(key)
            start = EPOCH + timedelta(days=rng.randint(0, 400), hours=rng.randint(0, 10))
            cases.append(self._case(len(cases), values, start, split))
        return cases

    def _draw(self, rng: random.Random) -> dict[str, str]:
        for _ in range(200):
            values = {name: rng.choice(list(options)) for name, options in self.slots.items()}
            if all(len({values[s] for s in group}) == len(group) for group in self.distinct):
                return values
        raise ValueError(f"{self.id}: distinct constraint unsatisfiable")

    def _case(self, index: int, values: dict[str, str], start: datetime, split: Split) -> Case:
        def fill(text: str) -> str:
            return text.format(**values)

        memories = [
            CaseMemory(
                id=m.id,
                content=fill(m.text),
                observed_at=start + timedelta(days=m.day),
                sequence=i,
                label=m.label,
                durability=m.durability,
            )
            for i, m in enumerate(self.memories)
        ]
        return Case(
            case_id=f"{self.id}/i{index}",
            dataset=DATASET,
            split=split,
            category=self.category,
            family=self.id,
            user_id=f"{self.id}/i{index}",
            now=start + timedelta(days=self.query_day),
            memories=memories,
            query=fill(self.query),
            intent=self.intent,
            expected=ExpectedAnswer(
                mode=self.answer.mode,
                aliases=[fill(a) for a in self.answer.aliases],
                forbidden=[fill(f) for f in self.answer.forbidden],
            ),
            relations=[
                GoldRelation(earlier=e, later=later, relation=r) for e, later, r in self.relations
            ],
            background_eligible=self.background,
        )
