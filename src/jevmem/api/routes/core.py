"""API v1 routes: system, chat, memories, recall/judge/compare, demo, benchmark."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from jevmem import __version__
from jevmem.api.schemas import (
    BenchmarkRunRequest,
    ChatRequest,
    ChatResponse,
    CompareRequest,
    DemoRequest,
    MemoryCreate,
    RecallRequest,
)
from jevmem.config import Settings
from jevmem.judgment.questions import QUESTION_SCHEMA_VERSION
from jevmem.memory.demo import QUERIES
from jevmem.memory.models import MemoryStatus
from jevmem.memory.service import MemoryService, RecallOutcome
from jevmem.policy.thresholds import POLICY_VERSION

router = APIRouter(prefix="/api/v1")


def service(request: Request) -> MemoryService:
    svc: MemoryService = request.app.state.service
    return svc


def settings(request: Request) -> Settings:
    s: Settings = request.app.state.settings
    return s


def _debug(outcome: RecallOutcome, s: Settings) -> dict[str, Any] | None:
    return outcome.model_dump(mode="json") if s.expose_debug else None


# --- system ----------------------------------------


@router.get("/health")
def health(svc: MemoryService = Depends(service)) -> dict[str, Any]:
    breakers = {
        name: {"state": client.breaker.state, "last_error": client.breaker.last_error}
        for name, client in svc.clients.items()
        if getattr(client, "breaker", None) is not None
    }
    return {
        "status": "ok",
        "version": __version__,
        "jev_configured": svc.judge_configured,
        "qwen_configured": svc.generator is not None,
        "embeddings": svc.embedder is not None,
        "circuit": breakers,
    }


@router.get("/config/public")
def config_public(
    svc: MemoryService = Depends(service), s: Settings = Depends(settings)
) -> dict[str, Any]:
    return {
        "settings": s.public_dict(),
        "modes": svc.available_modes(),
        "default_mode": s.default_retrieval_mode,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "policy": svc.policy.model_dump(mode="json"),
        "debug_payloads": s.expose_debug,
    }


@router.get("/metrics/summary")
def metrics_summary(svc: MemoryService = Depends(service)) -> dict[str, Any]:
    clients = {name: client.stats.as_dict() for name, client in svc.clients.items()}
    return {"service": svc.metrics.summary(), "clients": clients}


@router.get("/users")
def users(svc: MemoryService = Depends(service)) -> list[str]:
    return svc.store.users()


# --- chat ----------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest, svc: MemoryService = Depends(service), s: Settings = Depends(settings)
) -> ChatResponse:
    out = await svc.chat(
        body.user_id,
        body.message,
        conversation_id=body.conversation_id,
        mode=body.mode,
        now=body.now,
        extract=body.extract,
    )
    return ChatResponse(
        conversation_id=out.conversation_id,
        answer=out.answer,
        extracted=[w.model_dump(mode="json") for w in out.extracted],
        extraction_error=out.extraction_error,
        latency_ms={
            "retrieval": round(out.recall.retrieval_ms, 1),
            "judge": round(out.recall.judge_ms, 1),
            "generation": round(out.generation_ms, 1),
        },
        memory_debug=_debug(out.recall, s),
    )


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: str, svc: MemoryService = Depends(service), s: Settings = Depends(settings)
) -> list[dict[str, Any]]:
    turns = svc.turns.history(conversation_id, limit=200)
    if not s.expose_debug:
        for t in turns:
            t["debug"] = None
    return turns


# --- memories ----------------------------------------


@router.post("/memories", status_code=201)
async def create_memory(
    body: MemoryCreate, svc: MemoryService = Depends(service)
) -> dict[str, Any]:
    written = await svc.add_memory(
        body.user_id,
        body.content,
        memory_type=body.memory_type,
        observed_at=body.observed_at,
        valid_until=body.valid_until,
        tags=body.tags,
        metadata=body.metadata,
    )
    return written.model_dump(mode="json")


@router.get("/memories")
def list_memories(
    user_id: str = Query(min_length=1, max_length=200),
    status: MemoryStatus | None = None,
    now: datetime | None = None,
    svc: MemoryService = Depends(service),
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    memories = svc.list_memories(user_id, [status] if status else None)
    return [{**m.model_dump(mode="json"), "validity": svc.validity(m, now).value} for m in memories]


@router.get("/memories/{memory_id}")
def get_memory(
    memory_id: str, now: datetime | None = None, svc: MemoryService = Depends(service)
) -> dict[str, Any]:
    return svc.lineage(memory_id, now).model_dump(mode="json")


@router.delete("/memories/{memory_id}")
def archive_memory(memory_id: str, svc: MemoryService = Depends(service)) -> dict[str, Any]:
    """Status transition to ARCHIVED; history and lineage are kept."""
    return svc.archive(memory_id).model_dump(mode="json")


# --- recall ----------------------------------------


@router.post("/retrieve")
async def retrieve(body: RecallRequest, svc: MemoryService = Depends(service)) -> dict[str, Any]:
    """First-stage candidates only (no judge)."""
    mode = body.mode or svc.settings.default_retrieval_mode
    candidates = await svc.first_stage(body.user_id, body.query, mode)
    return {"mode": mode, "candidates": [c.model_dump(mode="json") for c in candidates]}


@router.post("/judge")
async def judge(body: RecallRequest, svc: MemoryService = Depends(service)) -> dict[str, Any]:
    mode = body.mode or "hybrid"
    if mode not in ("jev", "hybrid"):
        raise HTTPException(status_code=422, detail="judge needs mode 'jev' or 'hybrid'")
    return (await svc.recall(body.user_id, body.query, mode, body.now)).model_dump(mode="json")


@router.post("/compare")
async def compare(body: CompareRequest, svc: MemoryService = Depends(service)) -> dict[str, Any]:
    modes = body.modes or svc.available_modes()
    results = await svc.compare(body.user_id, body.query, modes, body.now)
    return {m: r.model_dump(mode="json") for m, r in results.items()}


# --- demo ----------------------------------------


@router.get("/demo/queries")
def demo_queries() -> list[dict[str, str]]:
    return [q.model_dump() for q in QUERIES]


@router.post("/demo/seed")
async def demo_seed(
    body: DemoRequest, svc: MemoryService = Depends(service), s: Settings = Depends(settings)
) -> dict[str, Any]:
    if s.environment == "production":
        raise HTTPException(status_code=403, detail="demo seeding is disabled in production")
    written = await svc.seed_demo(body.user_id)
    return {"user_id": body.user_id, "memories": [w.model_dump(mode="json") for w in written]}


@router.post("/demo/reset")
def demo_reset(
    body: DemoRequest, svc: MemoryService = Depends(service), s: Settings = Depends(settings)
) -> dict[str, Any]:
    if s.environment == "production":
        raise HTTPException(status_code=403, detail="demo reset is disabled in production")
    return {"user_id": body.user_id, "removed": svc.reset_user(body.user_id)}


# --- benchmark ----------------------------------------

RESULTS = Path("benchmarks/results")


@router.post("/benchmark/run", status_code=202)
async def benchmark_run(
    body: BenchmarkRunRequest,
    request: Request,
    tasks: BackgroundTasks,
    s: Settings = Depends(settings),
) -> dict[str, Any]:
    from jevmem.benchmark.runner import ALL_SYSTEMS, RunConfig, run

    run_id = f"api-{body.split}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    config = RunConfig(
        run_id=run_id,
        cases_paths=[Path("benchmarks/datasets/synthetic-v1") / f"{body.split}.jsonl"],
        systems=body.systems or ALL_SYSTEMS,
        n_background=body.n_background,
        limit=body.limit,
        params_path=s.params_path,
    )
    status: dict[str, dict[str, Any]] = request.app.state.benchmarks
    status[run_id] = {"state": "running", "started": datetime.now(UTC).isoformat()}

    async def job() -> None:
        try:
            out = await run(config, s)
            status[run_id] = {**status[run_id], "state": "done", "results": str(out)}
        except Exception as exc:
            status[run_id] = {**status[run_id], "state": "failed", "error": type(exc).__name__}

    tasks.add_task(asyncio.create_task, job())
    return {"run_id": run_id, "state": "running"}


@router.get("/benchmark/runs")
def benchmark_runs(request: Request) -> list[dict[str, Any]]:
    runs = []
    for d in sorted(RESULTS.glob("*/metrics.json")):
        overall = json.loads(d.read_text(encoding="utf-8"))["overall"]
        runs.append(
            {
                "run_id": d.parent.name,
                "answer_accuracy": {k: v["answer_correct"]["mean"] for k, v in overall.items()},
            }
        )
    live = request.app.state.benchmarks
    return runs + [{"run_id": k, **v} for k, v in live.items() if v["state"] != "done"]


@router.get("/benchmark/runs/{run_id}")
def benchmark_run_detail(run_id: str) -> dict[str, Any]:
    path = RESULTS / run_id
    if not (path / "metrics.json").exists() or ".." in run_id:
        raise HTTPException(status_code=404, detail="unknown run")
    return {
        "run_id": run_id,
        "metrics": json.loads((path / "metrics.json").read_text(encoding="utf-8")),
        "manifest": json.loads((path / "manifest.json").read_text(encoding="utf-8")),
    }
