"""Shared HTTP plumbing: bounded concurrency, retries with backoff, error mapping."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from jevmem import __version__
from jevmem.providers.errors import (
    AuthenticationError,
    PaymentRequiredError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    RequestValidationError,
    ResponseFormatError,
)

# Some endpoints sit behind Cloudflare, which rejects the default Python-urllib signature.
USER_AGENT = f"jevmem/{__version__}"

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}

Sleep = Callable[[float], Awaitable[None]]


@dataclass
class ClientStats:
    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    errors: int = 0
    latency_ms_total: float = 0.0
    status_counts: dict[int, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "cache_hits": self.cache_hits,
            "retries": self.retries,
            "errors": self.errors,
            "latency_ms_total": round(self.latency_ms_total, 1),
            "status_counts": dict(self.status_counts),
        }


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 4
    backoff_base_s: float = 0.5
    backoff_max_s: float = 20.0

    def delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.backoff_max_s)
        exp: float = min(self.backoff_base_s * (2**attempt), self.backoff_max_s)
        jitter: float = 0.5 + random.random() / 2  # in [0.5, 1.0)
        return exp * jitter


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def _error_for(provider: str, status: int, body: str) -> ProviderError:
    message = body[:300] or "request failed"
    if status in (401, 403):
        return AuthenticationError(provider, message, status)
    if status == 402:
        return PaymentRequiredError(provider, message, status)
    if status == 429:
        return RateLimitedError(provider, message, status)
    if status in _RETRYABLE_STATUS:
        return ProviderUnavailableError(provider, message, status)
    return RequestValidationError(provider, message, status)


class SingleFlight:
    """Collapse concurrent identical requests (same cache key) into one in-flight call."""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[HttpOutcome]] = {}

    async def run(self, key: str, call: Callable[[], Awaitable[HttpOutcome]]) -> HttpOutcome:
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        future: asyncio.Future[HttpOutcome] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            outcome = await call()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved so an unawaited failure is not logged
            raise
        else:
            future.set_result(outcome)
            return outcome
        finally:
            del self._inflight[key]


@dataclass(frozen=True)
class HttpOutcome:
    body: dict[str, Any]
    latency_ms: float
    attempts: int


async def post_json_with_retries(
    client: httpx.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    *,
    provider: str,
    headers: Mapping[str, str],
    retry: RetryPolicy,
    stats: ClientStats,
    sleep: Sleep = asyncio.sleep,
) -> HttpOutcome:
    """POST `payload`; retry transient failures; map terminal failures to ProviderError."""
    attempt = 0
    while True:
        stats.requests += 1
        start = time.perf_counter()
        try:
            response = await client.post(url, json=payload, headers=dict(headers))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            error: ProviderError = ProviderUnavailableError(provider, type(exc).__name__)
            retry_after = None
        else:
            latency_ms = (time.perf_counter() - start) * 1000
            stats.status_counts[response.status_code] = (
                stats.status_counts.get(response.status_code, 0) + 1
            )
            if response.is_success:
                try:
                    body = response.json()
                except ValueError as exc:
                    stats.errors += 1
                    raise ResponseFormatError(provider, "non-JSON success body") from exc
                if not isinstance(body, dict):
                    stats.errors += 1
                    raise ResponseFormatError(provider, "expected a JSON object")
                stats.latency_ms_total += latency_ms
                return HttpOutcome(body, latency_ms, attempt + 1)
            error = _error_for(provider, response.status_code, response.text)
            retry_after = parse_retry_after(response.headers.get("retry-after"))

        if not error.retryable or attempt >= retry.max_retries:
            stats.errors += 1
            raise error
        stats.retries += 1
        await sleep(retry.delay(attempt, retry_after))
        attempt += 1
