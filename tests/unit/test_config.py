from pathlib import Path

import pytest

from jevmem.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("JEV_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_jev_key_falls_back_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, OPENROUTER_API_KEY="or-key")
    assert s.jev_api_key is not None
    assert s.jev_api_key.get_secret_value() == "or-key"


def test_explicit_jev_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, OPENROUTER_API_KEY="or-key", JEV_API_KEY="jev-key")
    assert s.jev_api_key is not None
    assert s.jev_api_key.get_secret_value() == "jev-key"


def test_public_dict_never_contains_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, OPENROUTER_API_KEY="super-secret", QWEN_API_KEY="also-secret")
    dumped = str(s.public_dict())
    assert "super-secret" not in dumped
    assert "also-secret" not in dumped


def test_public_dict_hides_endpoints_and_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(
        monkeypatch,
        QWEN_BASE_URL="https://private-gpu.example.internal/v1",
        DATABASE_URL="postgresql+psycopg://jevmem:hunter2@db.example.internal/jevmem",
    )
    public = s.public_dict()
    dumped = str(public)
    assert "private-gpu" not in dumped
    assert "hunter2" not in dumped
    assert "db.example.internal" not in dumped
    assert not any(k.endswith("_url") for k in public)
    assert public["database_backend"] == "postgresql"
    assert public["qwen_model"] == s.qwen_model


def test_defaults_route_jev_through_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch)
    assert s.jev_base_url == "https://openrouter.ai/api"
    assert s.cache_path == Path("data") / "cache" / "responses.sqlite3"
