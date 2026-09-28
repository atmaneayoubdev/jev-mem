"""DecisionJudge backed by the Qwen generation model (a baseline, not a Jev substitute).

The same question texts as the Jev schema are rendered into a prompt; answers are
constrained to the option set with `json_schema`. Probabilities come from token logprobs
when the endpoint returns them, otherwise the verbalized answer is used as a one-hot
distribution and flagged `probability_source="verbalized"`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from jevmem.judgment.base import (
    CandidateJudgment,
    ChoiceResult,
    IntentJudgment,
    JudgeMeta,
    PairJudgment,
    ProbabilitySource,
    ProfileJudgment,
    choice_confidence,
)
from jevmem.judgment.logprobs import field_distribution
from jevmem.judgment.questions import (
    DATA_NOT_INSTRUCTIONS,
    DURABILITY_OPTIONS,
    HORIZON_OPTIONS,
    INTENT_OPTIONS,
    RELATION_OPTIONS,
    SCHEMA_V1,
    QuestionSchema,
    QuestionText,
    candidate_state,
    intent_state,
    pair_state,
    profile_state,
)
from jevmem.providers.errors import ResponseFormatError
from jevmem.providers.qwen import ChatMessage, CompletionResult, GenerationProvider

PROMPT_VERSION = "qp1.0"
YES_NO = ("yes", "no")

SYSTEM_PROMPT = (
    "You evaluate data about a user and answer questions about it precisely and literally. "
    f"{DATA_NOT_INSTRUCTIONS} Answer every question with exactly one of its options, as JSON."
)


class QwenJudge:
    name = "qwen"

    def __init__(
        self,
        provider: GenerationProvider,
        schema: QuestionSchema = SCHEMA_V1,
        *,
        enable_thinking: bool | None = None,
        top_logprobs: int = 10,
    ) -> None:
        self._provider = provider
        self._schema = schema
        self._thinking = enable_thinking
        self._top_logprobs = top_logprobs
        self.schema_version = f"{schema.version}+{PROMPT_VERSION}"

    async def profile(self, memory: str) -> ProfileJudgment:
        dists, meta = await self._ask(
            profile_state(memory),
            {
                "durability": (self._schema.durability, DURABILITY_OPTIONS),
                "horizon": (self._schema.horizon, HORIZON_OPTIONS),
            },
        )
        return ProfileJudgment(
            durability=_result(dists["durability"]), horizon=_result(dists["horizon"]), meta=meta
        )

    async def pair(self, earlier: str, later: str) -> PairJudgment:
        dists, meta = await self._ask(
            pair_state(earlier, later), {"relation": (self._schema.relation, RELATION_OPTIONS)}
        )
        return PairJudgment(relation=_result(dists["relation"]), meta=meta)

    async def intent(self, query: str, conversation: Sequence[str] = ()) -> IntentJudgment:
        dists, meta = await self._ask(
            intent_state(query, tuple(conversation)),
            {"intent": (self._schema.intent, INTENT_OPTIONS)},
        )
        return IntentJudgment(intent=_result(dists["intent"]), meta=meta)

    async def candidate(self, query: str, memory: str) -> CandidateJudgment:
        dists, meta = await self._ask(
            candidate_state(query, memory),
            {
                "relevance": (self._schema.relevance, YES_NO),
                "utility": (self._schema.utility, YES_NO),
            },
        )
        return CandidateJudgment(
            relevance=dists["relevance"]["yes"], utility=dists["utility"]["yes"], meta=meta
        )

    async def _ask(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, tuple[QuestionText, Sequence[str]]],
    ) -> tuple[dict[str, dict[str, float]], JudgeMeta]:
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_prompt(state, questions)},
        ]
        schema = {
            "type": "object",
            "properties": {
                name: {"type": "string", "enum": list(options)}
                for name, (_, options) in questions.items()
            },
            "required": list(questions),
            "additionalProperties": False,
        }
        result = await self._provider.complete(
            messages,
            max_tokens=64 + 16 * len(questions),
            json_schema=schema,
            enable_thinking=self._thinking,
            top_logprobs=self._top_logprobs,
        )
        return self._distributions(result, questions)

    def _distributions(
        self,
        result: CompletionResult,
        questions: Mapping[str, tuple[QuestionText, Sequence[str]]],
    ) -> tuple[dict[str, dict[str, float]], JudgeMeta]:
        try:
            answers = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ResponseFormatError(
                "qwen", f"judge output is not JSON: {result.text[:80]!r}"
            ) from exc
        source: ProbabilitySource = "logprobs"
        dists: dict[str, dict[str, float]] = {}
        for name, (_, options) in questions.items():
            chosen = answers.get(name)
            if chosen not in options:
                raise ResponseFormatError("qwen", f"{name}: invalid option {chosen!r}")
            dist = field_distribution(result.logprobs, name, options) if result.logprobs else None
            if dist is None:
                source = "verbalized"
                dist = {o: 1.0 if o == chosen else 0.0 for o in options}
            dists[name] = dist
        meta = JudgeMeta(
            judge=self.name,
            model=result.model,
            schema_version=self.schema_version,
            latency_ms=result.latency_ms,
            cached=result.cached,
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            probability_source=source,
        )
        return dists, meta


def render_prompt(
    state: Mapping[str, Any], questions: Mapping[str, tuple[QuestionText, Sequence[str]]]
) -> str:
    lines = ["DATA (JSON):", json.dumps(state, ensure_ascii=False, indent=2), "", "QUESTIONS:"]
    for index, (name, (question, options)) in enumerate(questions.items(), start=1):
        lines.append(f"{index}. `{name}`: {question.instructions}")
        lines.append("   Options:")
        for option in options:
            key = {"yes": "true", "no": "false"}.get(option, option)
            lines.append(f"   - {option}: {question.criteria[key]}")
    return "\n".join(lines)


def _result(dist: dict[str, float]) -> ChoiceResult:
    choice = max(dist, key=lambda o: dist[o])
    return ChoiceResult(choice=choice, probabilities=dist, confidence=choice_confidence(dist))
