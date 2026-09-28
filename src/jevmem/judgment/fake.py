"""Deterministic judge for tests and offline smoke runs. Never used to produce results."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from jevmem.judgment.base import (
    CandidateJudgment,
    ChoiceResult,
    IntentJudgment,
    JudgeMeta,
    PairJudgment,
    ProfileJudgment,
    choice_confidence,
)
from jevmem.judgment.questions import (
    DURABILITY_OPTIONS,
    HORIZON_OPTIONS,
    INTENT_OPTIONS,
    RELATION_OPTIONS,
)
from jevmem.providers.errors import ProviderUnavailableError

Dist = dict[str, float]


def one_hot(options: Sequence[str], choice: str, p: float = 0.9) -> Dist:
    rest = (1.0 - p) / (len(options) - 1)
    return {o: p if o == choice else rest for o in options}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


class FakeJudge:
    name = "fake"
    schema_version = "fake"

    def __init__(
        self,
        *,
        candidate: Callable[[str, str], tuple[float, float]] | None = None,
        pair: Callable[[str, str], Dist] | None = None,
        intent: Callable[[str], Dist] | None = None,
        profile: Callable[[str], tuple[Dist, Dist]] | None = None,
        fail: bool = False,
    ) -> None:
        self._candidate = candidate or (lambda q, m: (min(1.0, 3 * overlap(q, m)),) * 2)
        self._pair = pair or (lambda e, later: one_hot(RELATION_OPTIONS, "unrelated"))
        self._intent = intent or (lambda q: one_hot(INTENT_OPTIONS, "current"))
        self._profile = profile or (
            lambda m: (one_hot(DURABILITY_OPTIONS, "lasting"), one_hot(HORIZON_OPTIONS, "weeks"))
        )
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def _meta(self) -> JudgeMeta:
        if self.fail:
            raise ProviderUnavailableError("fake", "simulated outage")
        return JudgeMeta(
            judge=self.name,
            model="fake",
            schema_version=self.schema_version,
            latency_ms=1.0,
            probability_source="fixture",
        )

    async def profile(self, memory: str) -> ProfileJudgment:
        self.calls.append(("profile", (memory,)))
        meta = self._meta()
        durability, horizon = self._profile(memory)
        return ProfileJudgment(durability=_result(durability), horizon=_result(horizon), meta=meta)

    async def pair(self, earlier: str, later: str) -> PairJudgment:
        self.calls.append(("pair", (earlier, later)))
        meta = self._meta()
        return PairJudgment(relation=_result(self._pair(earlier, later)), meta=meta)

    async def intent(self, query: str, conversation: Sequence[str] = ()) -> IntentJudgment:
        self.calls.append(("intent", (query,)))
        meta = self._meta()
        return IntentJudgment(intent=_result(self._intent(query)), meta=meta)

    async def candidate(
        self, query: str, memory: str, status: str | None = None
    ) -> CandidateJudgment:
        self.calls.append(("candidate", (query, memory)))
        meta = self._meta()
        relevance, utility = self._candidate(query, memory)
        return CandidateJudgment(relevance=relevance, utility=utility, meta=meta)


def _result(dist: Dist) -> ChoiceResult:
    choice = max(dist, key=lambda o: dist[o])
    return ChoiceResult(choice=choice, probabilities=dist, confidence=choice_confidence(dist))
