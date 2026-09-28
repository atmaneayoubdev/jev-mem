from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pytest

from jevmem.judgment.base import choice_confidence
from jevmem.judgment.jev_judge import JevJudge
from jevmem.judgment.logprobs import field_distribution
from jevmem.judgment.questions import SCHEMA_V1
from jevmem.judgment.qwen_judge import QwenJudge, render_prompt
from jevmem.providers.errors import ResponseFormatError
from jevmem.providers.jev import SystemOneClient
from jevmem.providers.qwen import ChatMessage, CompletionResult, TokenLogprob


def test_choice_confidence_matches_jev_reported_values() -> None:
    # Live Jev answer: supersedes .95 / contradicts .05 / 0 / 0 -> confidence 0.93
    assert choice_confidence({"a": 0.95, "b": 0.05, "c": 0.0, "d": 0.0}) == pytest.approx(
        0.9333, abs=1e-3
    )
    assert choice_confidence({"a": 1.0, "b": 0.0, "c": 0.0}) == 1.0
    assert choice_confidence({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}) == pytest.approx(0.0)


def _tok(token: str, logprob: float, *alts: tuple[str, float]) -> TokenLogprob:
    return TokenLogprob(token=token, logprob=logprob, top=[(token, logprob), *alts])


def test_field_distribution_reads_value_token_alternatives() -> None:
    tokens = [
        _tok('{"', -0.0),
        _tok("relevance", -0.0),
        _tok('":', -0.0),
        _tok(' "', -0.0),
        _tok("yes", -0.1, ("no", -2.4)),
        _tok('",', -0.0),
        _tok(' "', -0.0),
        _tok("utility", -0.0),
        _tok('":', -0.0),
        _tok(' "', -0.0),
        _tok("no", -0.3, ("yes", -1.4)),
        _tok('"}', -0.0),
    ]
    rel = field_distribution(tokens, "relevance", ("yes", "no"))
    util = field_distribution(tokens, "utility", ("yes", "no"))
    assert rel is not None
    assert util is not None
    assert rel["yes"] == pytest.approx(0.9089, abs=1e-3)
    assert util["no"] == pytest.approx(0.7503, abs=1e-3)


def test_field_distribution_handles_quote_fused_tokens_and_subword_options() -> None:
    tokens = [
        _tok('{"relation": ', -0.0),
        _tok('"sup', -0.2, ('"contr', -1.8), ('"un', -4.0)),
        _tok('ersedes"}', -0.0),
    ]
    dist = field_distribution(tokens, "relation", ("supersedes", "contradicts", "unrelated"))
    assert dist is not None
    assert max(dist, key=lambda o: dist[o]) == "supersedes"
    assert sum(dist.values()) == pytest.approx(1.0)
    assert field_distribution(tokens, "missing", ("a", "b")) is None


JEV_CANDIDATE = {
    "model": "typesafe/jev-1.13-20260917",
    "answers": {
        "relevance": {"type": "noul", "noul": 0.9},
        "utility": {"type": "noul", "noul": 0.2},
    },
    "usage": {"input_tokens": 400, "output_tokens": 20, "cost": 0.00002},
}


async def test_jev_judge_candidate_state_and_meta() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=JEV_CANDIDATE)

    client = SystemOneClient(
        api_key="k", base_url="https://x.test", model="m", transport=httpx.MockTransport(handler)
    )
    async with client:
        judgment = await JevJudge(client).candidate("Deploy my service.", "I prefer AWS.")
    assert seen[0]["state"] == {"query": "Deploy my service.", "memory": "I prefer AWS."}
    assert set(seen[0]["questions"]) == {"relevance", "utility"}
    assert "criteria" in seen[0]["questions"]["utility"]
    assert judgment.relevance == 0.9
    assert judgment.utility == 0.2
    assert judgment.meta.model == "typesafe/jev-1.13-20260917"
    assert judgment.meta.schema_version == SCHEMA_V1.version
    assert judgment.meta.cost == 0.00002


async def test_jev_judge_rejects_wrong_answer_type() -> None:
    body = {"model": "m", "answers": {"relation": {"type": "noul", "noul": 0.5}}}
    client = SystemOneClient(
        api_key="k",
        base_url="https://x.test",
        model="m",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    async with client:
        with pytest.raises(ResponseFormatError, match="expected a choice"):
            await JevJudge(client).pair("a", "b")


class StubProvider:
    model = "qwen-test"

    def __init__(self, text: str, logprobs: list[TokenLogprob] | None) -> None:
        self.text = text
        self.logprobs = logprobs
        self.requests: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: Mapping[str, Any] | None = None,
        enable_thinking: bool | None = None,
        top_logprobs: int | None = None,
    ) -> CompletionResult:
        self.requests.append(
            {"messages": messages, "schema": json_schema, "top_logprobs": top_logprobs}
        )
        return CompletionResult(
            text=self.text,
            model=self.model,
            logprobs=self.logprobs,
            latency_ms=5.0,
            attempts=1,
            cached=False,
            prompt_tokens=100,
            completion_tokens=10,
        )


async def test_qwen_judge_uses_logprobs_when_available() -> None:
    tokens = [
        _tok('{"intent": "', -0.0),
        _tok("hist", -0.4, ("current", -1.2), ("both", -3.0)),
        _tok('orical"}', 0.0),
    ]
    provider = StubProvider('{"intent": "historical"}', tokens)
    judgment = await QwenJudge(provider).intent("What did I use before?")
    assert judgment.intent.choice == "historical"
    assert judgment.meta.probability_source == "logprobs"
    assert 0.5 < judgment.intent.p("historical") < 0.7
    schema = provider.requests[0]["schema"]
    assert schema["properties"]["intent"]["enum"] == ["current", "historical", "both"]


async def test_qwen_judge_falls_back_to_verbalized() -> None:
    provider = StubProvider('{"relevance": "yes", "utility": "no"}', None)
    judgment = await QwenJudge(provider).candidate("q", "m")
    assert (judgment.relevance, judgment.utility) == (1.0, 0.0)
    assert judgment.meta.probability_source == "verbalized"


async def test_qwen_judge_rejects_invalid_option() -> None:
    provider = StubProvider('{"relation": "maybe"}', None)
    with pytest.raises(ResponseFormatError, match="invalid option"):
        await QwenJudge(provider).pair("a", "b")


def test_render_prompt_includes_every_option_criterion() -> None:
    prompt = render_prompt(
        {"query": "q", "memory": "m"},
        {"utility": (SCHEMA_V1.utility, ("yes", "no"))},
    )
    assert SCHEMA_V1.utility.criteria["true"] in prompt
    assert SCHEMA_V1.utility.criteria["false"] in prompt
    assert '"memory": "m"' in prompt
