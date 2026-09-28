"""Benchmark orchestration: materialize → select → answer → score → write artifacts."""

from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from jevmem.benchmark.answer import ANSWER_PROMPT_VERSION, AnswerResult, generate_answer
from jevmem.benchmark.datasets.background import load_pool
from jevmem.benchmark.datasets.schema import Case
from jevmem.benchmark.e2e import extract_cases
from jevmem.benchmark.grading import GRADER_VERSION, grade
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
from jevmem.benchmark.scoring import AnswerScore
from jevmem.benchmark.systems import SYSTEMS, Params, Selection, available, select
from jevmem.benchmark.variants import ablation_variants, budget_variants, pool_variants
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
    # Stratified subset (saturation sweep): first N families per category, M instances each.
    families_per_category: int | None = None
    instances_per_family: int | None = None
    params_path: Path | None = None
    cache_mode: CacheMode = "readwrite"
    background_path: Path = Path("benchmarks/datasets/background-v1.jsonl")
    results_dir: Path = Path("benchmarks/results")
    # Override supersede_mode for judged systems. LongMemEval uses "annotate": one turn holds
    # several facts, so a superseded turn is flagged in context rather than withheld.
    supersede_mode: Literal["exclude", "annotate"] | None = None
    # Pre-registered secondary analyses (extra "systems" from the same materials)
    budgets: list[int] = Field(default_factory=list)
    pools: list[int] = Field(default_factory=list)
    ablations: bool = False
    # End-to-end track: case memories and distractors replayed as user turns through Qwen
    # extraction before the normal pipeline (see benchmark/e2e.py).
    e2e: bool = False


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
        readonly_judges=("jev",) if config.ablations and "jev" in judges else (),
    )
    models = {
        "jev_requested": settings.jev_model if "jev" in judges else None,
        "qwen": settings.qwen_model,
        "embedding": settings.embedding_model if embedder else None,
        "reranker": settings.reranker_model if reranker else None,
    }
    return Runtime(resources=resources, generator=generator, stack=stack, models=models)


def load_params(path: Path | None, supersede_mode: str | None = None) -> Params:
    params = (
        Params()
        if path is None or not path.exists()
        else Params.model_validate_json(path.read_text(encoding="utf-8"))
    )
    if supersede_mode is not None:
        for name, cfg in params.policy.items():
            params.policy[name] = cfg.model_copy(update={"supersede_mode": supersede_mode})
    return params


def load_cases(
    paths: Sequence[Path],
    limit: int | None,
    families_per_category: int | None = None,
    instances_per_family: int | None = None,
) -> list[Case]:
    cases: list[Case] = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            cases += [Case.model_validate_json(line) for line in fh if line.strip()]
    if families_per_category is not None or instances_per_family is not None:
        fams: dict[str, list[str]] = {}
        for c in cases:
            if c.family not in fams.setdefault(c.category, []):
                fams[c.category].append(c.family)
        keep = {f for fs in fams.values() for f in fs[: families_per_category or len(fs)]}
        seen: dict[str, int] = {}
        subset = []
        for c in cases:
            if c.family in keep and seen.get(c.family, 0) < (instances_per_family or 10**9):
                seen[c.family] = seen.get(c.family, 0) + 1
                subset.append(c)
        cases = subset
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
    materials: Sequence[CaseMaterials],
    systems: Sequence[str],
    params: Params,
    budget: int,
    config: RunConfig | None = None,
) -> list[tuple[CaseMaterials, Selection]]:
    out = []
    for mat in materials:
        for spec in available(systems, mat):
            out.append((mat, select(spec, mat, params, budget)))
        if config is not None:
            extra = budget_variants(mat, params, config.budgets)
            extra += pool_variants(mat, params, budget, config.pools)
            if config.ablations:
                extra += ablation_variants(mat, params, budget)
            out += [(mat, sel) for sel in extra]
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


async def grade_all(
    pairs: Sequence[tuple[CaseMaterials, Selection]],
    answers: Sequence[AnswerResult | None],
    grader: OpenAICompatibleProvider | None,
) -> list[AnswerScore | None]:
    """LLM-judge grading for cases whose expected answer is `llm_judge` (e.g. LongMemEval)."""

    async def one(mat: CaseMaterials, answer: AnswerResult | None) -> AnswerScore | None:
        exp = mat.case.expected
        if grader is None or answer is None or exp.mode != "llm_judge":
            return None
        try:
            return await grade(
                grader,
                task=exp.task or "",
                question=mat.case.query,
                reference=exp.reference or "",
                answer=answer.answer,
                abstention=exp.abstention,
            )
        except ProviderError:
            return None

    pending = (one(m, a) for (m, _), a in zip(pairs, answers, strict=True))
    return list(await asyncio.gather(*pending))


def _jsonl(path: Path, rows: Sequence[BaseModel]) -> None:
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8", newline="\n") as gz:
            for row in rows:
                gz.write(row.model_dump_json() + "\n")
        return
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
    cases = load_cases(
        config.cases_paths, config.limit, config.families_per_category, config.instances_per_family
    )
    params = load_params(config.params_path, config.supersede_mode)
    runtime = await build_runtime(config, settings)
    extraction_stats = None
    async with runtime.stack:
        n_background = config.n_background
        if config.e2e:
            if runtime.generator is None:
                raise RuntimeError("the e2e track needs the Qwen generator")
            cases, stats = await extract_cases(
                cases, runtime.resources.background, config.n_background, runtime.generator
            )
            extraction_stats = stats.model_dump()
            n_background = 0  # distractors were already replayed as turns
        materials = await materialize_all(
            cases,
            runtime.resources,
            n_background=n_background,
            pool_max=config.pool_max,
            concurrency=config.case_concurrency,
            progress=(lambda d, t: progress("materialize", d, t)) if progress else None,
        )
        pairs = select_all(materials, config.systems, params, config.budget, config)
        answers = await answer_all(pairs, runtime.generator if config.answer else None)
        grades = await grade_all(pairs, answers, runtime.generator)
    results = [
        case_result(mat.case, sel, ans, grade)
        for (mat, sel), ans, grade in zip(pairs, answers, grades, strict=True)
    ]
    relations: list[RelationOutcome] = []
    durability: list[DurabilityOutcome] = []
    for mat in materials:
        for judged in mat.judged.values():
            if not judged.reports:  # read-only ablation store: no write-time lifecycle
                continue
            r, d = lifecycle_outcomes(mat.case, judged)
            relations += r
            durability += d
    return write_run(
        config, params, materials, results, relations, durability, runtime.models, extraction_stats
    )


def write_run(
    config: RunConfig,
    params: Params,
    materials: Sequence[CaseMaterials],
    results: Sequence[CaseResult],
    relations: Sequence[RelationOutcome],
    durability: Sequence[DurabilityOutcome],
    models: dict[str, str | None],
    extraction_stats: dict[str, Any] | None = None,
) -> Path:
    out = config.results_dir / config.run_id
    out.mkdir(parents=True, exist_ok=True)
    _jsonl(out / "cases.jsonl.gz", results)  # raw per-case rows are large; gzip (~10x smaller)
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
        grader_version=GRADER_VERSION,
        params=params.model_dump(mode="json"),
        datasets=datasets,
        background_sha256=file_sha256(config.background_path),
        cases=len({r.case_id for r in results}),
        extraction=extraction_stats,
        judge_failures={
            name: sum(1 for m in materials if m.judged.get(name) and m.judged[name].failure)
            for name in config.judges
        },
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    return out


async def materialize_only(config: RunConfig, settings: Settings) -> list[CaseMaterials]:
    """Materials without answers (calibration, ablations, probes)."""
    cases = load_cases(
        config.cases_paths, config.limit, config.families_per_category, config.instances_per_family
    )
    runtime = await build_runtime(config, settings)
    async with runtime.stack:
        return await materialize_all(
            cases,
            runtime.resources,
            n_background=config.n_background,
            pool_max=config.pool_max,
            concurrency=config.case_concurrency,
        )
