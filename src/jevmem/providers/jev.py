"""TypeSafe System One client (Jev).

Implements the documented contract at `POST {base_url}/v1/systemone`:

    {"model": str, "state": str | object | array, "questions": {name: Question}}

Answers per question type (docs.typesafe.ai/api, verified live 2026-09-28):
- noul:   {"type": "noul", "noul": p}                    (no `confidence` field)
- choice: {"type": "choice", "choice": str, "probabilities": {...}, "confidence": c}
- score:  {"type": "score", "score": x, "probabilities": {...}, "confidence": c, "legend": {...}}

The default base URL routes through OpenRouter's Decisions API, which uses the same
shape and adds `id`, `provider`, and `usage.cost`. This is deliberately *not* a
chat-completions client.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import TracebackType
from typing import Annotated, Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jevmem.providers.cache import ResponseCache, cache_key
from jevmem.providers.errors import CacheMissError, ResponseFormatError
from jevmem.providers.http import (
    USER_AGENT,
    ClientStats,
    RetryPolicy,
    Sleep,
    post_json_with_retries,
)

PROVIDER = "jev"

Instructions = str | dict[str, Any] | list[Any]
State = str | dict[str, Any] | list[Any]


# --- Questions ---------------------------------------------------------------


class NoulCriteria(BaseModel):
    true: str
    false: str


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: Instructions
    criteria: NoulCriteria | None = None


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: Instructions
    criteria: dict[str, str] = Field(min_length=2, max_length=255)


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: Instructions
    criteria: list[str] = Field(min_length=2, max_length=10)


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


# --- Answers -----------------------------------------------------------------


class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["score"]
    score: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    legend: dict[str, Any] | None = None


Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None  # present when routed through OpenRouter


class SystemOneResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    answers: dict[str, Answer]
    usage: Usage = Field(default_factory=Usage)
    id: str | None = None
    provider: str | None = None


class SystemOneResult(BaseModel):
    response: SystemOneResponse
    latency_ms: float  # as originally measured, also when served from cache
    attempts: int
    cached: bool


# --- Client ------------------------------------------------------------------


class SystemOneClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_concurrency: int = 16,
        timeout_s: float = 30.0,
        retry: RetryPolicy | None = None,
        cache: ResponseCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retry = retry or RetryPolicy()
        self._cache = cache
        self._sleep = sleep
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self.stats = ClientStats()

    async def evaluate(
        self,
        state: State,
        questions: Mapping[str, NoulQuestion | ChoiceQuestion | ScoreQuestion],
        *,
        model: str | None = None,
    ) -> SystemOneResult:
        if not questions:
            raise ValueError("at least one question is required")
        payload: dict[str, Any] = {
            "model": model or self.model,
            "state": state,
            "questions": {
                name: q.model_dump(mode="json", exclude_none=True) for name, q in questions.items()
            },
        }
        key = cache_key(PROVIDER, payload)
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                self.stats.cache_hits += 1
                return SystemOneResult(
                    response=self._parse(hit.response, questions),
                    latency_ms=hit.latency_ms,
                    attempts=0,
                    cached=True,
                )
            if self._cache.mode == "replay":
                raise CacheMissError(PROVIDER, f"no cached response for {key[:12]}")

        async with self._semaphore:
            outcome = await post_json_with_retries(
                self._client,
                self._url,
                payload,
                provider=PROVIDER,
                headers=self._headers,
                retry=self._retry,
                stats=self.stats,
                sleep=self._sleep,
            )
        response = self._parse(outcome.body, questions)
        if self._cache is not None:
            self._cache.put(
                key,
                provider=PROVIDER,
                requested_model=payload["model"],
                resolved_model=response.model,
                response=outcome.body,
                latency_ms=outcome.latency_ms,
            )
        return SystemOneResult(
            response=response,
            latency_ms=outcome.latency_ms,
            attempts=outcome.attempts,
            cached=False,
        )

    @staticmethod
    def _parse(body: dict[str, Any], questions: Mapping[str, object]) -> SystemOneResponse:
        try:
            response = SystemOneResponse.model_validate(body)
        except ValidationError as exc:
            raise ResponseFormatError(PROVIDER, f"unexpected response shape: {exc}") from exc
        missing = set(questions) - set(response.answers)
        if missing:
            raise ResponseFormatError(PROVIDER, f"answers missing for {sorted(missing)}")
        return response

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
