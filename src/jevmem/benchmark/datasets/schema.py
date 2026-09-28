"""Benchmark case format (JSONL, one case per line).

Gold labels are only ever read by the scorer. The systems under test receive memory
contents, observation times, the query, and `now`: never labels, categories, families,
or expected answers (spec §34).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["required", "forbidden", "neutral"]
Split = Literal["dev", "calib", "test"]
AnswerMode = Literal["value", "abstain", "conflict", "all"]
Relation = Literal["supersedes", "contradicts", "duplicate", "refines", "unrelated"]


class CaseMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    content: str
    observed_at: datetime
    sequence: int = 0
    label: Label
    # Gold write-time facts, for lifecycle metrics only.
    durability: Literal["lasting", "temporary", "event"] | None = None


class GoldRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    earlier: str
    later: str
    relation: Relation


class ExpectedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: AnswerMode = "value"
    # value: any alias counts; all: every value must appear; conflict: flag or name all values
    aliases: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    dataset: str  # e.g. "synthetic-v1", "longmemeval-s"
    split: Split
    category: str
    family: str
    user_id: str
    now: datetime
    memories: list[CaseMemory]
    query: str
    intent: Literal["current", "historical", "both"]
    expected: ExpectedAnswer
    relations: list[GoldRelation] = Field(default_factory=list)
    # When True, background distractors are inserted around the case memories.
    background_eligible: bool = True

    def ids_with(self, label: Label) -> set[str]:
        return {m.id for m in self.memories if m.label == label}
