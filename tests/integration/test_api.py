"""REST API with injected fakes (no network): routing, lifecycle, errors, security guards."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jevmem.api.app import create_app
from jevmem.bootstrap import App
from jevmem.config import Settings
from jevmem.database.repository import SqlMemoryStore, TurnStore
from jevmem.database.session import init_db, make_engine, make_sessionmaker
from jevmem.judgment.fake import FakeJudge, one_hot, overlap
from jevmem.judgment.questions import RELATION_OPTIONS
from jevmem.memory.service import MemoryService
from jevmem.policy.thresholds import PolicyConfig
from jevmem.providers.qwen import ChatMessage, CompletionResult

AWS = "My preferred cloud provider is AWS."
AZURE = "We finished migrating to Azure; Azure is my preferred cloud provider now."


class ScriptedGenerator:
    """Chat: echoes a reply naming the memories it saw. Extraction: stores 'I ...' sentences."""

    model = "fake-qwen"

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
        last = messages[-1]["content"]
        if json_schema is not None and "memories" in json_schema.get("properties", {}):
            turn = last.split("User turn to extract from:\n", 1)[-1].split("\n\n", 1)[0]
            items = (
                [{"content": turn, "type": "preference", "temporary": False, "evidence": turn}]
                if turn.startswith("I ")
                else []
            )
            text = json.dumps({"memories": items})
        else:
            system = messages[0]["content"]
            text = "Azure" if "Azure" in system else "no memory"
        return CompletionResult(
            text=text, model=self.model, latency_ms=3.0, attempts=1, cached=False
        )


def pair_rule(earlier: str, later: str) -> dict[str, float]:
    return one_hot(
        RELATION_OPTIONS,
        "supersedes" if ("AWS" in earlier and "Azure" in later) else "unrelated",
        0.95,
    )


def candidate_rule(query: str, memory: str) -> tuple[float, float]:
    score = (
        0.9
        if ("cloud" in memory.lower() and "cloud" in query.lower())
        else min(1.0, 3 * overlap(query, memory))
    )
    return score, score


def make_client(tmp_path: Path, **settings_kw: Any) -> TestClient:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        embeddings_enabled=False,
        **settings_kw,
    )  # type: ignore[call-arg]
    engine = make_engine(settings.database_url)
    init_db(engine)
    sessions = make_sessionmaker(engine)
    service = MemoryService(
        settings,
        SqlMemoryStore(sessions),
        TurnStore(sessions),
        judge=FakeJudge(pair=pair_rule, candidate=candidate_rule),
        generator=ScriptedGenerator(),
        embedder=None,
        policy=PolicyConfig(),
    )
    return TestClient(
        create_app(
            settings,
            bundle=App(service=service, stack=AsyncExitStack(), jev_client=None, qwen=None),
        )
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path) as c:
        yield c


def test_health_and_config(client: TestClient) -> None:
    health = client.get("/api/v1/health").json()
    assert health["status"] == "ok"
    assert health["jev_configured"] is True
    cfg = client.get("/api/v1/config/public").json()
    assert "embedding" not in cfg["modes"]  # no embedder configured
    assert "jev_api_key" not in cfg["settings"]
    assert client.get("/api/v1/health").headers["x-request-id"]


def test_memory_lifecycle_through_api(client: TestClient) -> None:
    r1 = client.post(
        "/api/v1/memories",
        json={"user_id": "u1", "content": AWS, "observed_at": "2026-01-01T09:00:00Z"},
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/api/v1/memories",
        json={"user_id": "u1", "content": AZURE, "observed_at": "2026-06-01T09:00:00Z"},
    )
    assert r2.json()["relations"][0]["action"] == "supersedes"
    memories = {
        m["content"]: m for m in client.get("/api/v1/memories", params={"user_id": "u1"}).json()
    }
    assert memories[AWS]["status"] == "superseded"
    assert memories[AZURE]["validity"] == "current"
    lineage = client.get(f"/api/v1/memories/{memories[AWS]['id']}").json()
    assert [m["content"] for m in lineage["chain"]] == [AWS, AZURE]

    old = client.post(
        "/api/v1/memories",
        json={"user_id": "u1", "content": "late", "observed_at": "2025-01-01T00:00:00Z"},
    )
    assert old.status_code == 409
    assert old.json()["error"] == "out_of_order"

    archived = client.delete(f"/api/v1/memories/{memories[AZURE]['id']}").json()
    assert archived["status"] == "archived"
    assert client.get("/api/v1/memories/nope").status_code == 404


def test_judge_compare_and_chat(client: TestClient) -> None:
    client.post(
        "/api/v1/memories",
        json={"user_id": "u2", "content": AWS, "observed_at": "2026-01-01T09:00:00Z"},
    )
    client.post(
        "/api/v1/memories",
        json={"user_id": "u2", "content": AZURE, "observed_at": "2026-06-01T09:00:00Z"},
    )
    judged = client.post(
        "/api/v1/judge",
        json={"user_id": "u2", "query": "Deploy on my preferred cloud", "mode": "hybrid"},
    ).json()
    decisions = {
        c["content"]: d["decision"]
        for d in judged["judgments"]
        for c in judged["candidates"]
        if c["id"] == d["id"]
    }
    assert decisions[AWS] == "stale"
    assert decisions[AZURE] == "use"

    compare = client.post(
        "/api/v1/compare",
        json={"user_id": "u2", "query": "Deploy on my preferred cloud", "modes": ["bm25", "jev"]},
    ).json()
    assert set(compare) == {"bm25", "jev"}
    assert len(compare["bm25"]["selected_ids"]) == 2  # similarity keeps both versions
    assert len(compare["jev"]["selected_ids"]) == 1

    candidates = client.post(
        "/api/v1/retrieve", json={"user_id": "u2", "query": "preferred cloud", "mode": "bm25"}
    ).json()
    assert len(candidates["candidates"]) == 2

    chat = client.post(
        "/api/v1/chat",
        json={
            "user_id": "u2",
            "message": "I prefer aisle seats on long flights.",
            "mode": "hybrid",
        },
    ).json()
    assert chat["extracted"][0]["memory"]["content"] == "I prefer aisle seats on long flights."
    assert chat["memory_debug"]["mode"] == "hybrid"
    history = client.get(f"/api/v1/conversations/{chat['conversation_id']}").json()
    assert [t["role"] for t in history] == ["user", "assistant"]
    assert (
        client.get("/api/v1/metrics/summary").json()["service"]["counters"]["memories_written"] >= 3
    )


def test_demo_seed_and_reset(client: TestClient) -> None:
    seeded = client.post("/api/v1/demo/seed", json={"user_id": "alex"}).json()
    assert len(seeded["memories"]) == 13
    assert any(m["instruction_like"] is False for m in seeded["memories"])
    assert len(client.get("/api/v1/demo/queries").json()) == 6
    assert client.post("/api/v1/demo/reset", json={"user_id": "alex"}).json()["removed"] == 13


def test_guards_size_rate_and_production_debug(tmp_path: Path) -> None:
    with make_client(tmp_path, max_request_bytes=1000) as c:
        big = c.post(
            "/api/v1/memories",
            content=json.dumps({"user_id": "u", "content": "x" * 3000}),
            headers={"content-type": "application/json"},
        )
        assert big.status_code == 413
        bad = c.post("/api/v1/memories", json={"user_id": "bad id!", "content": "x"})
        assert bad.status_code == 422
    with make_client(tmp_path / "rl", rate_limit_per_minute=2) as c:
        codes = [c.get("/api/v1/health").status_code for _ in range(3)]
        assert codes[-1] == 429
    with make_client(tmp_path / "prod", environment="production") as c:
        chat = c.post(
            "/api/v1/chat", json={"user_id": "u", "message": "hello", "extract": False}
        ).json()
        assert chat["memory_debug"] is None
        assert c.post("/api/v1/demo/seed", json={}).status_code == 403


def test_empty_memories_and_provider_failures(tmp_path: Path) -> None:
    from jevmem.providers.errors import ProviderUnavailableError

    class DownGenerator(ScriptedGenerator):
        async def complete(self, *args: Any, **kwargs: Any) -> CompletionResult:
            raise ProviderUnavailableError("qwen", "down")

    with make_client(tmp_path) as c:
        empty = c.post(
            "/api/v1/judge", json={"user_id": "nobody", "query": "anything", "mode": "hybrid"}
        ).json()
        assert empty["candidates"] == []
        assert empty["selected_ids"] == []
        svc = c.app.state.service  # type: ignore[attr-defined]
        c.post("/api/v1/memories", json={"user_id": "u3", "content": AWS})
        svc.judge.fail = True  # Jev outage: recall falls back, never fakes judgments
        chat = c.post(
            "/api/v1/chat", json={"user_id": "u3", "message": "Which cloud?", "extract": False}
        ).json()
        assert chat["memory_debug"]["judge_used"] is False
        assert chat["memory_debug"]["fallback_reason"]
        assert {j["decision"] for j in chat["memory_debug"]["judgments"]} <= {"unjudged", "drop"}
        svc.generator = DownGenerator()  # Qwen outage: clean 503, no silent model switch
        down = c.post("/api/v1/chat", json={"user_id": "u3", "message": "hi", "extract": False})
        assert down.status_code == 503
        assert down.json()["error"] == "service_unavailable"


def test_error_shapes_time_travel_and_turn_records(client: TestClient) -> None:
    bad = client.post("/api/v1/judge", json={"user_id": "u", "query": "q", "mode": "bm25"})
    assert bad.status_code == 422
    assert bad.json()["error"] == "http_error"
    invalid = client.post("/api/v1/memories", json={"user_id": "u"})
    assert invalid.status_code == 422
    body = invalid.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert body["request_id"]

    client.post(
        "/api/v1/memories",
        json={
            "user_id": "tt",
            "content": "I'm in Paris this week.",
            "observed_at": "2026-01-01T09:00:00Z",
        },
    )
    later = client.get(
        "/api/v1/memories", params={"user_id": "tt", "now": "2026-01-02T00:00:00Z"}
    ).json()
    assert later[0]["validity"] in ("current", "expired")  # fake judge: lasting -> current
    chat = client.post(
        "/api/v1/chat", json={"user_id": "tt", "message": "I like tea.", "mode": "jev"}
    ).json()
    turns = client.get(f"/api/v1/conversations/{chat['conversation_id']}").json()
    assistant = turns[-1]
    assert assistant["role"] == "assistant"
    assert "generation_ms" in assistant["debug"]
    assert assistant["debug"]["extracted"][0]["memory"]["content"] == "I like tea."
