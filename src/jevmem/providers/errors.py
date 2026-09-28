"""Provider error hierarchy shared by the Jev and Qwen clients."""

from __future__ import annotations


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
