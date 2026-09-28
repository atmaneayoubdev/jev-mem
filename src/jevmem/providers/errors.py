"""Provider error hierarchy shared by the Jev and Qwen clients."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://[^\s\"'<>]+")
_LONG_ID = re.compile(r"\b[0-9a-fA-F]{24,}\b")


class ProviderError(Exception):
    """Base class. `retryable` errors have already exhausted their retry budget when raised."""

    retryable = False

    def __init__(self, provider: str, message: str, status: int | None = None) -> None:
        super().__init__(f"[{provider}] {message}" + (f" (HTTP {status})" if status else ""))
        self.provider = provider
        self.status = status


class AuthenticationError(ProviderError):
    pass


class PaymentRequiredError(ProviderError):
    """402: e.g. the OpenRouter wallet is empty."""


class RequestValidationError(ProviderError):
    """400/422: the request itself is malformed; retrying will not help."""


class RateLimitedError(ProviderError):
    retryable = True


class ProviderUnavailableError(ProviderError):
    """5xx, 529 (overloaded), timeouts, and connection failures."""

    retryable = True


class ResponseFormatError(ProviderError):
    """The endpoint answered 2xx but with a body we cannot interpret."""


class CacheMissError(ProviderError):
    """Raised in cache-only (replay) mode when a request has no cached response."""


def redact(text: str) -> str:
    """Strip URLs and long hex ids (account / key identifiers) from provider error bodies.

    Keeps the actionable reason (e.g. "Key limit exceeded (monthly limit)") for the operator.
    """
    return _LONG_ID.sub("<id>", _URL.sub("<url>", text))


def public_message(exc: BaseException) -> str:
    """A short description safe to return to clients or publish in results.

    Provider error bodies can contain account details (e.g. OpenRouter includes the key's
    workspace URL and id), so they are logged server-side but never exposed.
    """
    if isinstance(exc, ProviderError):
        status = f" (HTTP {exc.status})" if exc.status else ""
        return f"{exc.provider} {type(exc).__name__}{status}"
    return type(exc).__name__
