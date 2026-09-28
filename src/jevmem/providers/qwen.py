"""Generation provider for an OpenAI-compatible chat endpoint (e.g. vLLM serving Qwen).

Used for answer generation, memory extraction, and the Qwen-as-judge baseline. Never
used as a silent substitute for Jev.

Observed endpoint behaviour (2026-09-28): behind Cloudflare (explicit User-Agent needed),
no `/models` route, reasoning model with a `reasoning` message field that can be turned
off via `chat_template_kwargs.enable_thinking`, `response_format: json_schema` supported,
`logprobs` / `top_logprobs` supported (also inside JSON-constrained output).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Literal, Protocol, Self, TypedDict

import httpx
from pydantic import BaseModel, Field

from jevmem.providers.cache import ResponseCache, cache_key
from jevmem.providers.errors import CacheMissError, ProviderError, ResponseFormatError
from jevmem.providers.http import (
    USER_AGENT,
    CircuitBreaker,
    ClientStats,
    HttpOutcome,
    RetryPolicy,
    SingleFlight,
    Sleep,
    post_json_with_retries,
)

PROVIDER = "qwen"


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class TokenLogprob(BaseModel):
    token: str
    logprob: float
    top: list[tuple[str, float]] = Field(default_factory=list)


class CompletionResult(BaseModel):
    text: str
    reasoning: str | None = None
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    logprobs: list[TokenLogprob] | None = None
    latency_ms: float
    attempts: int
    cached: bool


class GenerationProvider(Protocol):
    model: str

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: Mapping[str, Any] | None = None,
        enable_thinking: bool | None = None,
        top_logprobs: int | None = None,
    ) -> CompletionResult: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        max_concurrency: int = 16,
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
        enable_thinking: bool | None = False,
        cache: ResponseCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.model = model
        root = base_url.rstrip("/")
        self._url = (root if root.endswith("/v1") else root + "/v1") + "/chat/completions"
        self._headers = {"User-Agent": USER_AGENT}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retry = retry or RetryPolicy(max_retries=3)
        self._default_thinking = enable_thinking
        self._cache = cache
        self._sleep = sleep
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self.stats = ClientStats()
        self._flights = SingleFlight()
        self.breaker = breaker

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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        thinking = self._default_thinking if enable_thinking is None else enable_thinking
        if thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": thinking}
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": dict(json_schema)},
            }
        if top_logprobs is not None:
            payload["logprobs"] = True
            payload["top_logprobs"] = top_logprobs

        key = cache_key(PROVIDER, payload)
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                self.stats.cache_hits += 1
                return _parse(hit.response, hit.latency_ms, attempts=0, cached=True)
            if self._cache.mode == "replay":
                raise CacheMissError(PROVIDER, f"no cached response for {key[:12]}")

        async def call() -> HttpOutcome:
            async with self._semaphore:
                return await post_json_with_retries(
                    self._client,
                    self._url,
                    payload,
                    provider=PROVIDER,
                    headers=self._headers,
                    retry=self._retry,
                    stats=self.stats,
                    sleep=self._sleep,
                )

        if self.breaker is not None:
            self.breaker.check()
        try:
            outcome = await self._flights.run(key, call)
        except ProviderError as exc:
            if self.breaker is not None:
                self.breaker.record_failure(exc)
            raise
        if self.breaker is not None:
            self.breaker.record_success()
        result = _parse(outcome.body, outcome.latency_ms, attempts=outcome.attempts, cached=False)
        if self._cache is not None:
            self._cache.put(
                key,
                provider=PROVIDER,
                requested_model=self.model,
                resolved_model=result.model,
                response=outcome.body,
                latency_ms=outcome.latency_ms,
            )
        return result

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _parse(
    body: dict[str, Any], latency_ms: float, *, attempts: int, cached: bool
) -> CompletionResult:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ResponseFormatError(PROVIDER, "response has no choices[0].message") from exc
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    logprobs = None
    raw_lp = (choice.get("logprobs") or {}).get("content")
    if raw_lp:
        logprobs = [
            TokenLogprob(
                token=t["token"],
                logprob=t["logprob"],
                top=[(c["token"], c["logprob"]) for c in t.get("top_logprobs") or []],
            )
            for t in raw_lp
        ]
    return CompletionResult(
        text=(message.get("content") or "").strip(),
        reasoning=message.get("reasoning") or message.get("reasoning_content"),
        model=body.get("model") or "",
        finish_reason=choice.get("finish_reason"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        reasoning_tokens=details.get("reasoning_tokens"),
        logprobs=logprobs,
        latency_ms=latency_ms,
        attempts=attempts,
        cached=cached,
    )
