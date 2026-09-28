"""Provider clients against httpx.MockTransport: payload shape, retries, errors, caching."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from jevmem.providers.cache import ResponseCache
from jevmem.providers.errors import (
    AuthenticationError,
    CacheMissError,
    PaymentRequiredError,
    ProviderUnavailableError,
    RequestValidationError,
    ResponseFormatError,
)
from jevmem.providers.http import RetryPolicy
from jevmem.providers.jev import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulCriteria,
    NoulQuestion,
    SystemOneClient,
)
from jevmem.providers.qwen import OpenAICompatibleProvider

JEV_OK = {
    "id": "gen-dec-1",
    "model": "typesafe/jev-1.13-20260917",
    "provider": "TypeSafe",
    "answers": {
        "relevant": {"type": "noul", "noul": 0.91},
        "intent": {
            "type": "choice",
            "choice": "current",
            "probabilities": {"current": 0.9, "historical": 0.1},
            "confidence": 0.85,
        },
    },
    "usage": {"input_tokens": 300, "output_tokens": 20, "cost": 0.00001},
}
QUESTIONS = {
    "relevant": NoulQuestion(
        instructions="Is `memory` about `query`?", criteria=NoulCriteria(true="yes", false="no")
    ),
    "intent": ChoiceQuestion(
        instructions="Does `query` ask about now or the past?",
        criteria={"current": "now", "historical": "past"},
    ),
}

Handler = Callable[[httpx.Request], httpx.Response]


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def jev(
    handler: Handler,
    *,
    cache: ResponseCache | None = None,
    retries: int = 3,
    sleeps: Sleeps | None = None,
) -> SystemOneClient:
    return SystemOneClient(
        api_key="test-key",
        base_url="https://openrouter.test/api",
        model="typesafe/jev-1.13-20260917",
        transport=httpx.MockTransport(handler),
        retry=RetryPolicy(max_retries=retries, backoff_base_s=0.01),
        cache=cache,
        sleep=sleeps or Sleeps(),
    )


def sequence(*responses: httpx.Response | Exception) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


async def test_jev_payload_and_parsing() -> None:
    handler, seen = sequence(httpx.Response(200, json=JEV_OK))
    async with jev(handler) as client:
        result = await client.evaluate({"query": "q", "memory": "m"}, QUESTIONS)

    request = seen[0]
    assert request.url == "https://openrouter.test/api/v1/systemone"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["user-agent"].startswith("jevmem/")
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.13-20260917"
    assert body["state"] == {"query": "q", "memory": "m"}
    assert body["questions"]["relevant"] == {
        "type": "noul",
        "instructions": "Is `memory` about `query`?",
        "criteria": {"true": "yes", "false": "no"},
    }
    relevant = result.response.answers["relevant"]
    intent = result.response.answers["intent"]
    assert isinstance(relevant, NoulAnswer)
    assert relevant.noul == 0.91
    assert isinstance(intent, ChoiceAnswer)
    assert intent.confidence == 0.85
    assert result.response.usage.cost == 0.00001
    assert result.attempts == 1
    assert not result.cached


async def test_jev_retries_429_honoring_retry_after_then_succeeds() -> None:
    sleeps = Sleeps()
    handler, seen = sequence(
        httpx.Response(429, headers={"retry-after": "2"}, text="slow down"),
        httpx.Response(529, text="overloaded"),
        httpx.Response(200, json=JEV_OK),
    )
    async with jev(handler, sleeps=sleeps) as client:
        result = await client.evaluate("s", QUESTIONS)
    assert len(seen) == 3
    assert result.attempts == 3
    assert sleeps.calls[0] == 2.0  # honoured retry-after
    assert client.stats.retries == 2
    assert client.stats.status_counts == {429: 1, 529: 1, 200: 1}


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, AuthenticationError), (402, PaymentRequiredError), (422, RequestValidationError)],
)
async def test_jev_terminal_errors_do_not_retry(status: int, error: type[Exception]) -> None:
    handler, seen = sequence(httpx.Response(status, text="nope"))
    async with jev(handler) as client:
        with pytest.raises(error):
            await client.evaluate("s", QUESTIONS)
    assert len(seen) == 1


async def test_jev_timeout_exhausts_retries() -> None:
    handler, seen = sequence(*[httpx.ReadTimeout("t") for _ in range(3)])
    async with jev(handler, retries=2) as client:
        with pytest.raises(ProviderUnavailableError):
            await client.evaluate("s", QUESTIONS)
    assert len(seen) == 3
    assert client.stats.errors == 1


async def test_jev_missing_answer_is_a_format_error() -> None:
    body = {**JEV_OK, "answers": {"relevant": JEV_OK["answers"]["relevant"]}}  # type: ignore[index]
    handler, _ = sequence(httpx.Response(200, json=body))
    async with jev(handler) as client:
        with pytest.raises(ResponseFormatError, match="intent"):
            await client.evaluate("s", QUESTIONS)


async def test_jev_cache_replays_original_latency(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite3")
    handler, seen = sequence(httpx.Response(200, json=JEV_OK))
    async with jev(handler, cache=cache) as client:
        first = await client.evaluate("s", QUESTIONS)
        second = await client.evaluate("s", QUESTIONS)
    assert len(seen) == 1
    assert second.cached
    assert second.latency_ms == first.latency_ms
    assert second.response == first.response

    replay = ResponseCache(tmp_path / "c.sqlite3", mode="replay")
    handler2, seen2 = sequence()
    async with jev(handler2, cache=replay) as client:
        assert (await client.evaluate("s", QUESTIONS)).cached
        with pytest.raises(CacheMissError):
            await client.evaluate("other state", QUESTIONS)
    assert seen2 == []


async def test_jev_concurrency_is_bounded() -> None:
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json=JEV_OK)

    client = SystemOneClient(
        api_key="k",
        base_url="https://x.test",
        model="m",
        max_concurrency=3,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        await asyncio.gather(*(client.evaluate(f"s{i}", QUESTIONS) for i in range(12)))
    assert peak <= 3


def _qwen_body(content: str, **extra: Any) -> dict[str, Any]:
    return {
        "model": "qwen3.8-27b",
        "choices": [
            {"message": {"content": content, "reasoning": None}, "finish_reason": "stop", **extra}
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


async def test_qwen_payload_and_parsing() -> None:
    logprobs = {
        "content": [
            {
                "token": "yes",
                "logprob": -0.05,
                "top_logprobs": [
                    {"token": "yes", "logprob": -0.05},
                    {"token": "no", "logprob": -3.0},
                ],
            }
        ]
    }
    handler, seen = sequence(httpx.Response(200, json=_qwen_body("\n\nyes", logprobs=logprobs)))
    provider = OpenAICompatibleProvider(
        base_url="https://qwen.test/v1",
        api_key="qk",
        model="qwen3.8-27b",
        transport=httpx.MockTransport(handler),
    )
    async with provider:
        result = await provider.complete(
            [{"role": "user", "content": "hi"}],
            json_schema={"type": "object"},
            top_logprobs=5,
        )
    request = seen[0]
    assert request.url == "https://qwen.test/v1/chat/completions"
    assert request.headers["user-agent"].startswith("jevmem/")
    body = json.loads(request.content)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["type"] == "json_schema"
    assert body["logprobs"] is True
    assert body["top_logprobs"] == 5
    assert result.text == "yes"
    assert result.logprobs is not None
    assert result.logprobs[0].top == [("yes", -0.05), ("no", -3.0)]
    assert result.reasoning_tokens == 0


async def test_qwen_base_url_without_v1_and_cloudflare_block() -> None:
    handler, seen = sequence(httpx.Response(403, text="error code: 1010"))
    provider = OpenAICompatibleProvider(
        base_url="https://qwen.test",
        api_key=None,
        model="m",
        transport=httpx.MockTransport(handler),
    )
    async with provider:
        with pytest.raises(AuthenticationError, match="1010"):
            await provider.complete([{"role": "user", "content": "hi"}])
    assert seen[0].url == "https://qwen.test/v1/chat/completions"
    assert "authorization" not in seen[0].headers


async def test_concurrent_identical_requests_share_one_call() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=JEV_OK)

    client = SystemOneClient(
        api_key="k", base_url="https://x.test", model="m", transport=httpx.MockTransport(handler)
    )
    async with client:
        results = await asyncio.gather(*(client.evaluate("same", QUESTIONS) for _ in range(5)))
    assert calls == 1
    assert all(r.response == results[0].response for r in results)


async def test_circuit_breaker_opens_after_repeated_failures_and_half_opens() -> None:
    from jevmem.providers.http import CircuitBreaker

    breaker = CircuitBreaker("jev", failure_threshold=2, cooldown_s=0.1)
    handler, seen = sequence(
        *[httpx.Response(503, text="down") for _ in range(3)], httpx.Response(200, json=JEV_OK)
    )
    client = SystemOneClient(
        api_key="k",
        base_url="https://x.test",
        model="m",
        transport=httpx.MockTransport(handler),
        retry=RetryPolicy(max_retries=0),
        breaker=breaker,
        sleep=Sleeps(),
    )
    async with client:
        for i in range(2):
            with pytest.raises(ProviderUnavailableError):
                await client.evaluate(f"s{i}", QUESTIONS)
        assert breaker.state == "open"
        with pytest.raises(ProviderUnavailableError, match="circuit open"):
            await client.evaluate("s-open", QUESTIONS)
        assert len(seen) == 2  # fail fast: no request while open
        await asyncio.sleep(0.2)
        assert breaker.state == "half-open"
        with pytest.raises(ProviderUnavailableError):
            await client.evaluate("probe-1", QUESTIONS)  # failed probe re-opens
        assert breaker.state == "open"
        await asyncio.sleep(0.2)
        result = await client.evaluate("probe-2", QUESTIONS)  # successful probe closes
        assert result.response.model == JEV_OK["model"]
        assert breaker.state == "closed"
        assert breaker.opens == 1
