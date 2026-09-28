"""`jevmem` command-line interface."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jevmem.config import Settings, get_settings
from jevmem.memory.service import MemoryService
from jevmem.providers.errors import ProviderError
from jevmem.providers.factory import ConfigurationError, build_jev_client, build_qwen_provider
from jevmem.providers.jev import NoulAnswer, NoulQuestion

app = typer.Typer(
    help="JevMem: decision-native long-term memory for AI agents.", no_args_is_help=True
)
console = Console()


@app.callback()
def _root() -> None:
    """JevMem CLI."""


async def _check_jev(settings: Settings) -> tuple[bool, str]:
    try:
        client = build_jev_client(settings)
    except ConfigurationError as exc:
        return False, str(exc)
    async with client:
        try:
            result = await client.evaluate(
                "I was charged twice for my subscription.",
                {"refund": NoulQuestion(instructions="Is the customer asking for money back?")},
            )
        except ProviderError as exc:
            return False, str(exc)
    answer = result.response.answers["refund"]
    p = answer.noul if isinstance(answer, NoulAnswer) else float("nan")
    cost = result.response.usage.cost
    return True, (
        f"model={result.response.model} latency={result.latency_ms:.0f}ms "
        f"noul={p:.2f} tokens={result.response.usage.input_tokens}"
        + (f" cost=${cost:.6f}" if cost is not None else "")
    )


async def _check_qwen(settings: Settings) -> tuple[bool, str]:
    try:
        provider = build_qwen_provider(settings)
    except ConfigurationError as exc:
        return False, str(exc)
    async with provider:
        try:
            result = await provider.complete(
                [{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=16
            )
        except ProviderError as exc:
            return False, str(exc)
    ok = "OK" in result.text
    return ok, (
        f"model={result.model} latency={result.latency_ms:.0f}ms reply={result.text[:20]!r} "
        f"prompt_tokens={result.prompt_tokens} reasoning_tokens={result.reasoning_tokens}"
    )


def _check_database(settings: Settings) -> tuple[bool, str]:
    from sqlalchemy import func, select
    from sqlalchemy.exc import SQLAlchemyError

    from jevmem.database.models import MemoryRow
    from jevmem.database.session import init_db, make_engine

    try:
        engine = make_engine(settings.database_url)
        init_db(engine)
        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(MemoryRow)).scalar_one()
        engine.dispose()
    except SQLAlchemyError as exc:
        return False, f"{type(exc).__name__}"
    scheme = settings.database_url.split(":", 1)[0]
    return True, f"{scheme} ok, {count} memories"


def _check_data_dir(settings: Settings) -> tuple[bool, str]:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.data_dir, delete=True):
            pass
    except OSError as exc:
        return False, f"{settings.data_dir}: {exc.strerror}"
    return True, f"{settings.data_dir.resolve()} writable"


@app.command()
def doctor() -> None:
    """Check configuration and connectivity to Jev and Qwen. Never prints secrets."""
    settings = get_settings()
    jev_ok, jev_detail = asyncio.run(_check_jev(settings))
    qwen_ok, qwen_detail = asyncio.run(_check_qwen(settings))
    data_ok, data_detail = _check_data_dir(settings)
    db_ok, db_detail = _check_database(settings)
    rows = [
        ("data dir", data_ok, data_detail),
        ("database", db_ok, db_detail),
        (
            "jev key",
            settings.jev_api_key is not None,
            "present" if settings.jev_api_key else "missing",
        ),
        ("jev endpoint", jev_ok, f"{settings.jev_base_url} → {jev_detail}"),
        ("qwen endpoint", qwen_ok, qwen_detail),
    ]
    table = Table(title="jevmem doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for name, ok, detail in rows:
        table.add_row(name, "[green]ok[/]" if ok else "[red]fail[/]", detail)
    console.print(table)
    if not all(ok for _, ok, _ in rows):
        raise typer.Exit(code=1)


# --- benchmark ---------------------------------------------------------------------

benchmark_app = typer.Typer(help="Benchmark datasets, runs, and reports.", no_args_is_help=True)
app.add_typer(benchmark_app, name="benchmark")

DATASETS_DIR = Path("benchmarks/datasets")
SYNTHETIC_DIR = DATASETS_DIR / "synthetic-v1"
BACKGROUND_PATH = DATASETS_DIR / "background-v1.jsonl"


@benchmark_app.command("generate")
def benchmark_generate(
    splits: str = typer.Option("dev,calib,test", help="Comma-separated splits to build."),
) -> None:
    """Build the synthetic dataset from template families (deterministic)."""
    from jevmem.benchmark.datasets.synthetic.generate import build_all

    wanted = tuple(s.strip() for s in splits.split(",") if s.strip())
    manifest = build_all(SYNTHETIC_DIR, wanted)  # type: ignore[arg-type]
    for split, info in manifest.items():
        digest = info["sha256"][:12]
        console.print(
            f"{split}: {info['cases']} cases, {info['families']} families, sha256={digest}"
        )


@benchmark_app.command("generate-background")
def benchmark_generate_background(per_topic: int = typer.Option(30)) -> None:
    """Generate the shared background-distractor pool with Qwen (run once; output is committed)."""
    from jevmem.benchmark.datasets.background import generate_pool, save_pool

    async def run() -> int:
        async with build_qwen_provider(get_settings()) as provider:
            pool = await generate_pool(provider, per_topic=per_topic)
        save_pool(pool, BACKGROUND_PATH)
        return len(pool)

    console.print(f"wrote {asyncio.run(run())} background memories to {BACKGROUND_PATH}")


@benchmark_app.command("export-review")
def benchmark_export_review(
    split: str = typer.Option("dev"), per_family: int = typer.Option(1)
) -> None:
    """Write a readable markdown sample of cases for human review."""
    from jevmem.benchmark.datasets.synthetic.generate import load_split

    cases = load_split(SYNTHETIC_DIR / f"{split}.jsonl")
    shown: dict[str, int] = {}
    lines = [f"# Review sample: {split}", ""]
    for case in cases:
        if shown.get(case.family, 0) >= per_family:
            continue
        shown[case.family] = shown.get(case.family, 0) + 1
        lines += [
            f"## {case.case_id}  ·  {case.category}",
            "",
            "| label | date | memory |",
            "|---|---|---|",
        ]
        lines += [f"| {m.label} | {m.observed_at.date()} | {m.content} |" for m in case.memories]
        exp = case.expected
        lines += [
            "",
            f"**Query ({case.now.date()}, intent={case.intent}):** {case.query}",
            "",
            f"**Expected:** mode={exp.mode} aliases={exp.aliases} forbidden={exp.forbidden}",
            "",
        ]
    out = Path("benchmarks/review") / f"{split}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    console.print(f"wrote {out}")


@benchmark_app.command("run")
def benchmark_run(
    run_id: str = typer.Option(..., help="Name of the results directory."),
    split: list[str] = typer.Option(["dev"], help="Synthetic split(s) to run."),
    cases: list[Path] = typer.Option([], help="Explicit case JSONL files (overrides --split)."),
    supersede_mode: str | None = typer.Option(None, help="Override: exclude | annotate."),
    systems: str = typer.Option("all", help="Comma-separated system names, or 'all'."),
    judges: str = typer.Option("jev,qwen"),
    n_background: int = typer.Option(100),
    pool_max: int = typer.Option(20),
    budget: int = typer.Option(1024),
    limit: int | None = typer.Option(None, help="Stratified subset size (smoke runs)."),
    params: Path | None = typer.Option(None, help="Calibrated parameters JSON."),
    no_answer: bool = typer.Option(False, help="Skip answer generation."),
    no_embeddings: bool = typer.Option(False),
    replay: bool = typer.Option(False, help="Cache-only: fail on any uncached model call."),
    concurrency: int = typer.Option(8),
    budgets: str = typer.Option("", help="Budget sweep, e.g. '128,256,512'."),
    pools: str = typer.Option("", help="Pool-size sweep for hybrid-jev, e.g. '5,10,20,50'."),
    ablations: bool = typer.Option(False, help="Add hybrid-jev dimension ablations."),
    e2e: bool = typer.Option(False, help="End-to-end track: extract memories from raw turns."),
    families_per_category: int | None = typer.Option(None),
    instances_per_family: int | None = typer.Option(None),
) -> None:
    """Run the benchmark and write results to benchmarks/results/<run-id>/."""
    import json

    from jevmem.benchmark.reports import category_table, summary_table
    from jevmem.benchmark.runner import ALL_SYSTEMS, RunConfig, run

    config = RunConfig(
        run_id=run_id,
        cases_paths=cases or [SYNTHETIC_DIR / f"{s}.jsonl" for s in split],
        supersede_mode=supersede_mode,
        systems=ALL_SYSTEMS if systems == "all" else [s.strip() for s in systems.split(",")],
        judges=[j.strip() for j in judges.split(",") if j.strip()],
        n_background=n_background,
        pool_max=pool_max,
        budget=budget,
        embeddings=not no_embeddings,
        answer=not no_answer,
        case_concurrency=concurrency,
        limit=limit,
        params_path=params,
        cache_mode="replay" if replay else "readwrite",
        budgets=[int(b) for b in budgets.split(",") if b.strip()],
        pools=[int(p) for p in pools.split(",") if p.strip()],
        ablations=ablations,
        e2e=e2e,
        families_per_category=families_per_category,
        instances_per_family=instances_per_family,
    )

    def progress(stage: str, done: int, total: int) -> None:
        if done == total or done % max(1, total // 10) == 0:
            console.print(f"[dim]{stage}: {done}/{total}[/]")

    out = asyncio.run(run(config, get_settings(), progress=progress))
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    console.print(summary_table(metrics))
    console.print(category_table(metrics))
    console.print(f"results: {out}")


@benchmark_app.command("calibrate")
def benchmark_calibrate(
    split: str = typer.Option("calib"),
    n_background: int = typer.Option(100),
    budget: int = typer.Option(1024),
    out: Path = typer.Option(Path("benchmarks/params/calibrated-v1.json")),
    concurrency: int = typer.Option(8),
) -> None:
    """Grid-search every system's parameters on the calib split (offline over cached judgments)."""
    from jevmem.benchmark.calibrate import calibrate
    from jevmem.benchmark.runner import RunConfig, materialize_only

    if split == "test":
        raise typer.BadParameter("never calibrate on the test split")
    config = RunConfig(
        run_id=f"calibrate-{split}",
        cases_paths=[SYNTHETIC_DIR / f"{split}.jsonl"],
        n_background=n_background,
        budget=budget,
        answer=False,
        case_concurrency=concurrency,
    )
    materials = asyncio.run(materialize_only(config, get_settings()))
    report = calibrate(materials, budget)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.params.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    out.with_suffix(".grid.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8", newline="\n"
    )
    table = Table(title=f"calibration on {split} ({report.cases} cases)")
    for col in ("system", "best setting", "selection acc", "mean tokens"):
        table.add_column(col)
    for name, point in report.best.items():
        table.add_row(
            name, str(point.setting), f"{point.selection_accuracy:.3f}", f"{point.mean_tokens:.0f}"
        )
    console.print(table)
    console.print(f"wrote {out}")


@benchmark_app.command("probe")
def benchmark_probe(
    train: str = typer.Option("dev"), evaluate: str = typer.Option("calib")
) -> None:
    """Bag-of-words leakage probe: train on one split, evaluate on another."""
    from jevmem.benchmark.datasets.synthetic.generate import load_split
    from jevmem.benchmark.probes import run_probe

    result = run_probe(
        load_split(SYNTHETIC_DIR / f"{train}.jsonl"),
        load_split(SYNTHETIC_DIR / f"{evaluate}.jsonl"),
    )
    console.print(result.model_dump())


LME_SOURCE = Path("data/external/longmemeval/longmemeval_s_cleaned.json")
LME_CASES = Path("data/external/longmemeval/cases-preregistered.jsonl")


@benchmark_app.command("lme-prepare")
def benchmark_lme_prepare(
    source: Path = typer.Option(LME_SOURCE),
    out: Path = typer.Option(LME_CASES),
    limit: int | None = typer.Option(None),
) -> None:
    """Convert LongMemEval_S (pre-registered subsets) into JevMem cases."""
    from jevmem.benchmark.datasets.longmemeval import prepare

    console.print(f"wrote {prepare(source, out, limit=limit)} LongMemEval cases to {out}")


@benchmark_app.command("nondeterminism")
def benchmark_nondeterminism(
    split: str = typer.Option("test"),
    n: int = typer.Option(50, help="Number of cases (stratified)."),
    n_background: int = typer.Option(100),
    budget: int = typer.Option(1024),
    params: Path = typer.Option(Path("benchmarks/params/calibrated-v1.json")),
    out: Path = typer.Option(Path("benchmarks/results/nondeterminism.json")),
) -> None:
    """Re-issue Jev read-time judgments without the cache and measure decision flips."""
    from jevmem.benchmark.nondeterminism import check
    from jevmem.benchmark.runner import RunConfig, load_params, materialize_only
    from jevmem.judgment.jev_judge import JevJudge

    config = RunConfig(
        run_id=f"nondeterminism-{split}",
        cases_paths=[SYNTHETIC_DIR / f"{split}.jsonl"],
        judges=["jev"],
        n_background=n_background,
        answer=False,
        limit=n,
        case_concurrency=16,
        params_path=params,
    )
    settings = get_settings()

    async def go() -> str:
        materials = await materialize_only(config, settings)
        async with build_jev_client(settings, cache=None) as client:
            report = await check(materials, JevJudge(client), load_params(params), budget)
        return report.model_dump_json(indent=2)

    text = asyncio.run(go())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    console.print(text)


@benchmark_app.command("report")
def benchmark_report(
    run_id: str = typer.Option(...),
    primary: str = typer.Option("hybrid-jev,embedding", help="Pre-registered pair: a,b"),
    no_charts: bool = typer.Option(False),
) -> None:
    """(Re)generate report.md and charts for a run from its raw files."""
    from jevmem.benchmark.reports import write_report

    a, b = (s.strip() for s in primary.split(","))
    out = write_report(Path("benchmarks/results") / run_id, primary=(a, b), charts=not no_charts)
    console.print(f"wrote {out}")


# --- server, memories, demo --------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
) -> None:
    """Run the JevMem API server (and the built frontend, if present)."""
    import uvicorn

    from jevmem.observability.logging import configure_logging

    configure_logging(get_settings().log_level)
    uvicorn.run("jevmem.api.app:create_app", factory=True, host=host, port=port, reload=reload)


memory_app = typer.Typer(help="Inspect and add memories.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
demo_app = typer.Typer(help="Seed or reset the Alex demo scenario.", no_args_is_help=True)
app.add_typer(demo_app, name="demo")


def _run_with_service[T](fn: Callable[[MemoryService], Awaitable[T]]) -> T:
    from jevmem.bootstrap import build_app

    async def go() -> T:
        bundle = await build_app(get_settings())
        try:
            return await fn(bundle.service)
        finally:
            await bundle.aclose()

    return asyncio.run(go())


@memory_app.command("add")
def memory_add(
    user_id: str = typer.Option(..., "--user"),
    content: str = typer.Argument(...),
    memory_type: str = typer.Option("other", "--type"),
) -> None:
    """Add a memory through the write-time lifecycle (judge + policy)."""
    from jevmem.memory.models import MemoryType

    async def fn(svc: MemoryService) -> None:
        written = await svc.add_memory(user_id, content, memory_type=MemoryType(memory_type))
        console.print(f"[green]stored[/] {written.memory.id} durability={written.durability}")
        for rel in written.relations:
            console.print(
                f"  vs {rel['earlier_id']}: {rel['relation']} -> {rel['action']} ({rel['reason']})"
            )

    _run_with_service(fn)


@memory_app.command("list")
def memory_list(user_id: str = typer.Option(..., "--user")) -> None:
    """List a user's memories with lifecycle status and current validity."""

    async def fn(svc: MemoryService) -> None:
        table = Table(title=f"memories for {user_id}")
        for col in ("observed", "status", "validity", "durability", "content"):
            table.add_column(col, overflow="fold")
        for m in svc.list_memories(user_id):
            table.add_row(
                m.observed_at.date().isoformat(),
                m.status.value,
                svc.validity(m).value,
                (m.durability.value if m.durability else "-")
                + (" ⚠ instruction" if m.instruction_like else ""),
                m.content,
            )
        console.print(table)

    _run_with_service(fn)


@demo_app.command("seed")
def demo_seed(user_id: str = typer.Option("alex", "--user")) -> None:
    """(Re)create the Alex scenario through the real lifecycle."""

    async def fn(svc: MemoryService) -> None:
        written = await svc.seed_demo(user_id)
        console.print(f"seeded {len(written)} memories for {user_id}")
        for w in written:
            links = [f"{r['action']}→{r['earlier_id'][:6]}" for r in w.relations if r["action"]]
            console.print(
                f"  {w.memory.observed_at.date()} {w.durability or '-':9} "
                f"{'; '.join(links)}  {w.memory.content[:70]}"
            )

    _run_with_service(fn)


@demo_app.command("reset")
def demo_reset(user_id: str = typer.Option("alex", "--user")) -> None:
    """Remove the demo user's memories and conversations."""

    async def fn(svc: MemoryService) -> None:
        console.print(f"removed {svc.reset_user(user_id)} memories for {user_id}")

    _run_with_service(fn)
