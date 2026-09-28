"""Build provider clients from `Settings`. The only place secrets are unwrapped."""

from __future__ import annotations

from jevmem.config import Settings
from jevmem.providers.cache import ResponseCache
from jevmem.providers.http import CircuitBreaker, RetryPolicy
from jevmem.providers.jev import SystemOneClient
from jevmem.providers.qwen import OpenAICompatibleProvider


class ConfigurationError(RuntimeError):
    pass


def build_jev_client(settings: Settings, cache: ResponseCache | None = None) -> SystemOneClient:
    if settings.jev_api_key is None:
        raise ConfigurationError(
            "No Jev API key: set JEV_API_KEY, OPENROUTER_API_KEY, or TYPESAFE_API_KEY."
        )
    return SystemOneClient(
        api_key=settings.jev_api_key.get_secret_value(),
        base_url=settings.jev_base_url,
        model=settings.jev_model,
        max_concurrency=settings.jev_max_concurrency,
        timeout_s=settings.jev_timeout_s,
        retry=RetryPolicy(max_retries=settings.jev_max_retries),
        cache=cache,
        breaker=CircuitBreaker(
            "jev", settings.circuit_failure_threshold, settings.circuit_cooldown_s
        ),
    )


def build_qwen_provider(
    settings: Settings, cache: ResponseCache | None = None
) -> OpenAICompatibleProvider:
    if not settings.qwen_base_url or not settings.qwen_model:
        raise ConfigurationError("Qwen is not configured: set QWEN_BASE_URL and QWEN_MODEL.")
    return OpenAICompatibleProvider(
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key.get_secret_value() if settings.qwen_api_key else None,
        model=settings.qwen_model,
        max_concurrency=settings.qwen_max_concurrency,
        timeout_s=settings.qwen_timeout_s,
        retry=RetryPolicy(max_retries=settings.qwen_max_retries),
        enable_thinking=settings.qwen_enable_thinking,
        cache=cache,
        breaker=CircuitBreaker(
            "qwen", settings.circuit_failure_threshold, settings.circuit_cooldown_s
        ),
    )
