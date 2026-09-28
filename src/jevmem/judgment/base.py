"""Judgment interface and result types.

A `DecisionJudge` answers four kinds of generic questions. It never decides behaviour:
the deterministic policies in `jevmem.policy` turn these probabilities into actions.

- profile:   how long a memory's content stays true (write time, per memory)
- pair:      how a later memory relates to an earlier one (write time, per pair)
- intent:    what time frame a query needs (read time, per query)
- candidate: relevance and utility of a memory for a query (read time, per candidate)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, Field

ProbabilitySource = Literal["model", "logprobs", "verbalized", "fixture"]


def choice_confidence(probabilities: Mapping[str, float]) -> float:
    """Spread-based confidence: 1.0 when all mass is on one option, 0.0 when uniform.

    Equals (k * p_max - 1) / (k - 1). This reproduces the `confidence` Jev reports for
    choice answers (e.g. p_max=0.95 over 4 options -> 0.93), so both judges are comparable.
    """
    k = len(probabilities)
    if k < 2:
        return 1.0
    p_max = max(probabilities.values())
    return max(0.0, min(1.0, (k * p_max - 1) / (k - 1)))


class ChoiceResult(BaseModel):
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    def p(self, option: str) -> float:
        return self.probabilities.get(option, 0.0)


class JudgeMeta(BaseModel):
    judge: str  # "jev", "qwen", "fake"
    model: str  # model id reported by the server
    schema_version: str
    latency_ms: float
    cached: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    probability_source: ProbabilitySource = "model"


class ProfileJudgment(BaseModel):
    durability: ChoiceResult  # lasting | temporary | event
    horizon: ChoiceResult  # days | weeks | months (meaningful when temporary)
    meta: JudgeMeta


class PairJudgment(BaseModel):
    relation: ChoiceResult  # supersedes | contradicts | duplicate | refines | unrelated
    meta: JudgeMeta


class IntentJudgment(BaseModel):
    intent: ChoiceResult  # current | historical | both
    meta: JudgeMeta


class CandidateJudgment(BaseModel):
    relevance: float = Field(ge=0.0, le=1.0)
    utility: float = Field(ge=0.0, le=1.0)
    meta: JudgeMeta


class DecisionJudge(Protocol):
    name: str
    schema_version: str

    async def profile(self, memory: str) -> ProfileJudgment: ...

    async def pair(self, earlier: str, later: str) -> PairJudgment: ...

    async def intent(self, query: str, conversation: Sequence[str] = ()) -> IntentJudgment: ...

    async def candidate(
        self, query: str, memory: str, status: str | None = None
    ) -> CandidateJudgment: ...
