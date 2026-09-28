"""Real calls to Jev and Qwen. Run with `pytest -m live`; skipped when keys are missing."""

from __future__ import annotations

import pytest

from jevmem.config import Settings
from jevmem.providers.factory import build_jev_client, build_qwen_provider
from jevmem.providers.jev import ChoiceAnswer, ChoiceQuestion, NoulAnswer, NoulQuestion

pytestmark = pytest.mark.live

settings = Settings()


@pytest.mark.skipif(settings.jev_api_key is None, reason="no Jev key configured")
async def test_jev_live_noul_and_choice() -> None:
    async with build_jev_client(settings) as client:
        result = await client.evaluate(
            {"query": "Deploy my service to my preferred cloud.", "memory": "I prefer AWS."},
            {
                "relevance": NoulQuestion(instructions="Is `memory` about the subject of `query`?"),
                "intent": ChoiceQuestion(
                    instructions="Is `query` about the present or the past?",
                    criteria={"current": "The present or next steps.", "historical": "The past."},
                ),
            },
        )
    relevance = result.response.answers["relevance"]
    intent = result.response.answers["intent"]
    assert isinstance(relevance, NoulAnswer)
    assert 0.0 <= relevance.noul <= 1.0
    assert isinstance(intent, ChoiceAnswer)
    assert intent.choice in {"current", "historical"}
    assert abs(sum(intent.probabilities.values()) - 1.0) < 0.05
    assert result.response.model.startswith("typesafe/jev")
    assert result.response.usage.input_tokens > 0


@pytest.mark.skipif(not settings.qwen_base_url, reason="no Qwen endpoint configured")
async def test_qwen_live_json_schema_with_logprobs() -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
        "required": ["answer"],
    }
    async with build_qwen_provider(settings) as provider:
        result = await provider.complete(
            [{"role": "user", "content": "Is Paris in France? Answer in JSON."}],
            json_schema=schema,
            top_logprobs=5,
            max_tokens=32,
        )
    assert '"yes"' in result.text
    assert result.logprobs
    assert result.reasoning_tokens in (None, 0)
