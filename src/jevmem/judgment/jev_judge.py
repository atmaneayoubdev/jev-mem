"""DecisionJudge backed by TypeSafe Jev (System One)."""

from __future__ import annotations

from collections.abc import Sequence

from jevmem.judgment.base import (
    CandidateJudgment,
    ChoiceResult,
    IntentJudgment,
    JudgeMeta,
    PairJudgment,
    ProfileJudgment,
)
from jevmem.judgment.questions import (
    SCHEMA_V1,
    QuestionSchema,
    candidate_state,
    intent_state,
    pair_state,
    profile_state,
)
from jevmem.providers.errors import ResponseFormatError
from jevmem.providers.jev import ChoiceAnswer, NoulAnswer, SystemOneClient, SystemOneResult


class JevJudge:
    name = "jev"

    def __init__(self, client: SystemOneClient, schema: QuestionSchema = SCHEMA_V1) -> None:
        self._client = client
        self._schema = schema
        self.schema_version = schema.version

    async def profile(self, memory: str) -> ProfileJudgment:
        r = await self._client.evaluate(profile_state(memory), self._schema.jev_profile())
        return ProfileJudgment(
            durability=_choice(r, "durability"), horizon=_choice(r, "horizon"), meta=self._meta(r)
        )

    async def pair(self, earlier: str, later: str) -> PairJudgment:
        r = await self._client.evaluate(pair_state(earlier, later), self._schema.jev_pair())
        return PairJudgment(relation=_choice(r, "relation"), meta=self._meta(r))

    async def intent(self, query: str, conversation: Sequence[str] = ()) -> IntentJudgment:
        r = await self._client.evaluate(
            intent_state(query, tuple(conversation)), self._schema.jev_intent()
        )
        return IntentJudgment(intent=_choice(r, "intent"), meta=self._meta(r))

    async def candidate(
        self, query: str, memory: str, status: str | None = None
    ) -> CandidateJudgment:
        status = status if self._schema.candidate_status else None
        r = await self._client.evaluate(
            candidate_state(query, memory, status), self._schema.jev_candidate()
        )
        return CandidateJudgment(
            relevance=_noul(r, "relevance"), utility=_noul(r, "utility"), meta=self._meta(r)
        )

    def _meta(self, r: SystemOneResult) -> JudgeMeta:
        usage = r.response.usage
        return JudgeMeta(
            judge=self.name,
            model=r.response.model,
            schema_version=self.schema_version,
            latency_ms=r.latency_ms,
            cached=r.cached,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=usage.cost,
            probability_source="model",
        )


def _choice(r: SystemOneResult, name: str) -> ChoiceResult:
    answer = r.response.answers[name]
    if not isinstance(answer, ChoiceAnswer):
        raise ResponseFormatError("jev", f"{name}: expected a choice answer, got {answer.type}")
    return ChoiceResult(
        choice=answer.choice, probabilities=answer.probabilities, confidence=answer.confidence
    )


def _noul(r: SystemOneResult, name: str) -> float:
    answer = r.response.answers[name]
    if not isinstance(answer, NoulAnswer):
        raise ResponseFormatError("jev", f"{name}: expected a noul answer, got {answer.type}")
    return answer.noul
