"""Benchmark orchestration: materialize → select → answer → score → write artifacts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from jevmem.benchmark.answer import ANSWER_PROMPT_VERSION, AnswerResult, generate_answer
from jevmem.benchmark.datasets.background import load_pool
from jevmem.benchmark.datasets.schema import Case
from jevmem.benchmark.manifest import build_manifest, file_sha256
from jevmem.benchmark.materials import CaseMaterials, Resources, materialize
from jevmem.benchmark.metrics import (
    CaseResult,
    DurabilityOutcome,
    RelationOutcome,
    aggregate,
    aggregate_by_category,
    case_result,
    lifecycle_outcomes,
)
from jevmem.benchmark.systems import SYSTEMS, Params, Selection, available, select
from jevmem.config import Settings
from jevmem.judgment.base import DecisionJudge
from jevmem.judgment.jev_judge import JevJudge
from jevmem.judgment.questions import SCHEMA_V1
from jevmem.judgment.qwen_judge import QwenJudge
from jevmem.observability.logging import get_logger
from jevmem.policy.thresholds import POLICY_VERSION, PolicyConfig
from jevmem.providers.cache import CacheMode, ResponseCache
from jevmem.providers.errors import ProviderError
from jevmem.providers.factory import build_jev_client, build_qwen_provider
from jevmem.providers.qwen import OpenAICompatibleProvider
from jevmem.retrieval.embedding import EmbeddingCache, SentenceTransformerEmbedder
from jevmem.retrieval.rerank import CrossEncoderScorer

log = get_logger("benchmark")

ALL_SYSTEMS = list(SYSTEMS)


class RunConfig(BaseModel):
    run_id: str
    cases_paths: list[Path]
    systems: list[str] = Field(default_factory=lambda: list(ALL_SYSTEMS))
    judges: list[str] = Field(default_factory=lambda: ["jev", "qwen"])
    n_background: int = 100
    pool_max: int = 20
    budget: int = 1024
    embeddings: bool = True
    answer: bool = True
    case_concurrency: int = 8
    limit: int | None = None
    params_path: Path | None = None
    cache_mode: CacheMode = "readwrite"
    background_path: Path = Path("benchmarks/datasets/background-v1.jsonl")
    results_dir: Path = Path("benchmarks/results")


@dataclass
class Runtime:
    resources: Resources
    generator: OpenAICompatibleProvider | None
    stack: AsyncExitStack
    models: dict[str, str | None]


async def build_runtime(config: RunConfig, settings: Settings) -> Runtime:
    stack = AsyncExitStack()
    cache = ResponseCache(settings.cache_path, config.cache_mode)
    stack.callback(cache.close)
    judges: dict[str, DecisionJudge] = {}
    generator: OpenAICompatibleProvider | None = None
    if "jev" in config.judges:
        jev_client = await stack.enter_async_context(build_jev_client(settings, cache))
        judges["jev"] = JevJudge(jev_client)
    if "qwen" in config.judges or config.answer:
        generator = await stack.enter_async_context(build_qwen_provider(settings, cache))
        if "qwen" in config.judges:
            judges["qwen"] = QwenJudge(generator)
    embedder = reranker = None
    if config.embeddings:
        emb_cache = EmbeddingCache(settings.data_dir / "cache" / "embeddings.sqlite3")
        embedder = SentenceTransformerEmbedder(
            settings.embedding_model, cache=emb_cache, cache_queries=False
        )
        reranker = CrossEncoderScorer(settings.reranker_model, cache=emb_cache)
    params = load_params(config.params_path)
    resources = Resources(
        judges=judges,
        embedder=embedder,
        reranker=reranker,
        background=load_pool(config.background_path),
        write_policy=params.policy.get("jev", PolicyConfig()),
    )
    models = {
        "jev_requested": settings.jev_model if "jev" in judges else None,
        "qwen": settings.qwen_model,
        "embedding": settings.embedding_model if embedder else None,
        "reranker": settings.reranker_model if reranker else None,
    }
    return Runtime(resources=resources, generator=generator, stack=stack, models=models)


def load_params(path: Path | None) -> Params:
    if path is None or not path.exists():
        return Params()
    return Params.model_validate_json(path.read_text(encoding="utf-8"))


def load_cases(paths: Sequence[Path], limit: int | None) -> list[Case]:
    cases: list[Case] = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            cases += [Case.model_validate_json(line) for line in fh if line.strip()]
    if limit is not None:
        # stratified: first `limit` cases taken round-robin across families
        by_family: dict[str, list[Case]] = {}
        for c in cases:
            by_family.setdefault(c.family, []).append(c)
        ordered: list[Case] = []
        depth = max(len(g) for g in by_family.values())
        for i in range(depth):
            ordered += [group[i] for group in by_family.values() if i < len(group)]
        cases = ordered[:limit]
    return cases


async def materialize_all(
    cases: Sequence[Case],
    resources: Resources,
    *,
    n_background: int,
    pool_max: int,
    concurrency: int,
    progress: Callable[[int, int], None] | None = None,
) -> list[CaseMaterials]:
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def one(case: Case) -> CaseMaterials:
        nonlocal done
        async with semaphore:
            mat = await materialize(case, resources, n_background=n_background, pool_max=pool_max)
        done += 1
        if progress:
            progress(done, len(cases))
        return mat

    return list(await asyncio.gather(*(one(c) for c in cases)))


def select_all(
    materials: Sequence[CaseMaterials], systems: Sequence[str], params: Params, budget: int
) -> list[tuple[CaseMaterials, Selection]]:
    out = []
    for mat in materials:
        for spec in available(systems, mat):
            out.append((mat, select(spec, mat, params, budget)))
    return out


async def answer_all(
    pairs: Sequence[tuple[CaseMaterials, Selection]], generator: OpenAICompatibleProvider | None
) -> list[AnswerResult | None]:
    async def one(mat: CaseMaterials, sel: Selection) -> AnswerResult | None:
        if generator is None or sel.failure is not None:
            return None
        try:
            return await generate_answer(generator, mat.case.query, sel.context_text, mat.case.now)
        except ProviderError as exc:
            log.warning(
                "answer generation failed",
                extra={"case": mat.case.case_id, "system": sel.system, "error": type(exc).__name__},
            )
            return None

    return list(await asyncio.gather(*(one(m, s) for m, s in pairs)))


def _jsonl(path: Path, rows: Sequence[BaseModel]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(row.model_dump_json() + "\n")


def observed_models(materials: Sequence[CaseMaterials]) -> dict[str, list[str]]:
    seen: dict[str, set[str]] = {}
    for mat in materials:
        for name, judged in mat.judged.items():
            models = seen.setdefault(name, set())
            if judged.intent is not None:
                models.add(judged.intent.meta.model)
            models.update(j.meta.model for j in judged.candidates.values())
    return {k: sorted(v) for k, v in seen.items()}


async def run(
    config: RunConfig,
    settings: Settings,
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> Path:
    cases = load_cases(config.cases_paths, config.limit)
    params = load_params(config.params_path)
    runtime = await build_runtime(config, settings)
    async with runtime.stack:
        materials = await materialize_all(
            cases,
            runtime.resources,
            n_background=config.n_background,
            pool_max=config.pool_max,
            concurrency=config.case_concurrency,
            progress=(lambda d, t: progress("materialize", d, t)) if progress else None,
        )
        pairs = select_all(materials, config.systems, params, config.budget)
        answers = await answer_all(pairs, runtime.generator if config.answer else None)
    results = [
        case_result(mat.case, sel, ans) for (mat, sel), ans in zip(pairs, answers, strict=True)
    ]
    relations: list[RelationOutcome] = []
    durability: list[DurabilityOutcome] = []
    for mat in materials:
        for judged in mat.judged.values():
            r, d = lifecycle_outcomes(mat.case, judged)
            relations += r
            durability += d
    return write_run(config, params, materials, results, relations, durability, runtime.models)


def write_run(
    config: RunConfig,
    params: Params,
    materials: Sequence[CaseMaterials],
    results: Sequence[CaseResult],
    relations: Sequence[RelationOutcome],
    durability: Sequence[DurabilityOutcome],
    models: dict[str, str | None],
) -> Path:
    out = config.results_dir / config.run_id
    out.mkdir(parents=True, exist_ok=True)
    _jsonl(out / "cases.jsonl", results)
    _jsonl(out / "relations.jsonl", relations)
    _jsonl(out / "durability.jsonl", durability)
    metrics: dict[str, Any] = {
        "overall": {
            s: {m: e.model_dump() for m, e in ms.items()} for s, ms in aggregate(results).items()
        },
        "by_category": {
            c: {s: {m: e.model_dump() for m, e in ms.items()} for s, ms in systems.items()}
            for c, systems in aggregate_by_category(results).items()
        },
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    datasets = {str(p): file_sha256(p) for p in config.cases_paths}
    manifest = build_manifest(
        run=json.loads(config.model_dump_json()),
        models=models,
        models_observed=observed_models(materials),
        question_schema_version=SCHEMA_V1.version,
        policy_version=POLICY_VERSION,
        answer_prompt_version=ANSWER_PROMPT_VERSION,
        params=params.model_dump(mode="json"),
        datasets=datasets,
        background_sha256=file_sha256(config.background_path),
        cases=len({r.case_id for r in results}),
        judge_failures={
            name: sum(1 for m in materials if m.judged.get(name) and m.judged[name].failure)
            for name in config.judges
        },
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    return out
