"""Human-readable reports of a run: markdown tables, the pre-registered primary comparison,
lifecycle quality, calibration, failure buckets, and charts. Everything is recomputed from the
run's raw files, so a report can be regenerated at any time with `jevmem benchmark report`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jevmem.benchmark.reliability import relation_calibration, utility_calibration
from jevmem.benchmark.stats import Estimate, paired_cluster_bootstrap

HEADLINE = [
    ("answer_correct", "Answer acc.", True),
    ("selection_correct", "Selection acc.", True),
    ("forbidden_selected", "Forbidden in ctx", True),
    ("neutral_selected", "Neutral in ctx", False),
    ("context_tokens", "Ctx tokens", False),
    ("judge_ms", "Judge ms", False),
    ("end_to_end_ms", "E2E ms", False),
]
MAIN_SYSTEMS = [
    "hybrid-jev",
    "embedding-jev",
    "bm25-jev",
    "hybrid-qwen",
    "embedding",
    "embedding-threshold",
    "embedding-lifecycle",
    "embedding-decay",
    "rerank",
    "rerank-threshold",
    "bm25",
    "recency",
]


def _est(raw: dict[str, Any]) -> Estimate:
    return Estimate.model_validate(raw)


def summary_table(metrics: dict[str, Any], systems: Sequence[str] | None = None) -> str:
    overall = metrics["overall"]
    names = list(systems) if systems is not None else list(overall)
    header = "| System | " + " | ".join(label for _, label, _ in HEADLINE) + " | Failed |"
    lines = [header, "|" + "---|" * (len(HEADLINE) + 2)]
    for name in names:
        if name not in overall:
            continue
        row = overall[name]
        cells = [_est(row[key]).fmt(pct=pct, digits=1 if pct else 0) for key, _, pct in HEADLINE]
        lines.append(
            f"| {name} | " + " | ".join(cells) + f" | {int(row['failed_cases']['mean'])} |"
        )
    return "\n".join(lines)


def category_table(
    metrics: dict[str, Any], metric: str = "answer_correct", systems: Sequence[str] | None = None
) -> str:
    by_cat = metrics["by_category"]
    names = (
        list(systems)
        if systems is not None
        else sorted({s for cat in by_cat.values() for s in cat})
    )
    lines = ["| Category | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    for cat, rows in by_cat.items():
        cells = [_est(rows[s][metric]).fmt(digits=0) if s in rows else "-" for s in names]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _load(
    run: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    rel_path = run / "relations.jsonl"
    relations = (
        [json.loads(line) for line in rel_path.read_text(encoding="utf-8").splitlines() if line]
        if rel_path.exists()
        else []
    )
    return metrics, manifest, rows, relations


def _by_family(rows: Sequence[dict[str, Any]], system: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["system"] == system and not r["failed"] and r["score"] is not None:
            out[r["family"]].append(float(r["score"]["correct"]))
    return out


def primary_comparison(rows: Sequence[dict[str, Any]], a: str, b: str) -> str:
    try:
        est = paired_cluster_bootstrap(_by_family(rows, a), _by_family(rows, b), n_boot=5000)
    except ValueError:
        return f"Primary comparison {a} vs {b}: not enough shared families."
    if est.lo > 0:
        verdict = f"**{a} is better** (95% CI lower bound > 0)"
    elif est.hi < 0:
        verdict = f"**{a} is worse** (95% CI upper bound < 0)"
    else:
        verdict = "**no detectable difference** (95% CI contains 0)"
    return (
        f"Answer accuracy, {a} minus {b}: **{est.diff * 100:+.1f} pp** "
        f"[95% CI {est.lo * 100:+.1f}, {est.hi * 100:+.1f}] over {est.n_clusters} families "
        f"(paired family bootstrap, 5,000 resamples) -> {verdict}."
    )


def lifecycle_table(relations: Sequence[dict[str, Any]]) -> str:
    lines = [
        "| Judge | Supersession P | Supersession R | Contradiction P | Contradiction R | False supersession | Neighbour recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for judge in sorted({r["judge"] for r in relations}):
        rs = [r for r in relations if r["judge"] == judge]

        def pr(label: str, rs: list[dict[str, Any]] = rs) -> tuple[str, str]:
            tp = sum(1 for r in rs if r["gold"] == label and r["predicted"] == label)
            pred = sum(1 for r in rs if r["predicted"] == label)
            gold = sum(1 for r in rs if r["gold"] == label)
            return (f"{tp / pred:.2f}" if pred else "-", f"{tp / gold:.2f}" if gold else "-")

        sp, sr = pr("supersedes")
        cp, cr = pr("contradicts")
        unrelated = [r for r in rs if r["gold"] == "unrelated"]
        false_sup = sum(1 for r in unrelated if r["predicted"] == "supersedes")
        related = [r for r in rs if r["gold"] != "unrelated"]
        paired = sum(1 for r in related if r["paired"])
        lines.append(
            f"| {judge} | {sp} | {sr} | {cp} | {cr} | "
            f"{(false_sup / len(unrelated)) if unrelated else 0:.2f} ({false_sup}/{len(unrelated)}) | "
            f"{(paired / len(related)) if related else 0:.2f} ({paired}/{len(related)}) |"
        )
    return "\n".join(lines)


def calibration_table(
    rows: Sequence[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    relations: Sequence[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    results = []
    for system in ("hybrid-jev", "hybrid-qwen"):
        results += utility_calibration(rows, cases, system)
    for judge in ("jev", "qwen"):
        results.append(relation_calibration(relations, judge))
    lines = ["| Probabilities | n | ECE | Brier |", "|---|---|---|---|"]
    for r in results:
        if r.n:
            lines.append(f"| {r.name} | {r.n} | {r.ece:.3f} | {r.brier:.3f} |")
    return "\n".join(lines), {r.name: r for r in results}


def failure_buckets(
    rows: Sequence[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    a: str,
    b: str,
    examples: int = 3,
) -> str:
    by_case: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        if r["system"] in (a, b) and r["score"] is not None:
            by_case[r["case_id"]][r["system"]] = r
    buckets: dict[str, list[str]] = {
        f"{a} right, {b} wrong": [],
        f"{b} right, {a} wrong": [],
        "both wrong": [],
        "both right": [],
    }
    for cid, pair in by_case.items():
        if len(pair) < 2:
            continue
        ra, rb = pair[a]["score"]["correct"], pair[b]["score"]["correct"]
        key = (
            f"{a} right, {b} wrong"
            if ra and not rb
            else f"{b} right, {a} wrong"
            if rb and not ra
            else "both wrong"
            if not ra
            else "both right"
        )
        buckets[key].append(cid)
    lines = ["| Bucket | Cases |", "|---|---|"] + [
        f"| {k} | {len(v)} |" for k, v in buckets.items()
    ]
    for key in (f"{a} right, {b} wrong", f"{b} right, {a} wrong", "both wrong"):
        lines += ["", f"#### {key}"]
        if not buckets[key]:
            lines.append("_none_")
        seen_families: set[str] = set()
        shown = 0
        for cid in buckets[key]:
            case = cases.get(cid)
            if case is None or case["family"] in seen_families or shown >= examples:
                continue
            seen_families.add(case["family"])
            shown += 1
            lines += [
                "",
                f'**{cid}** ({case["category"]}). Query: "{case["query"]}". Expected: {case["expected"]["mode"]} {case["expected"]["aliases"][:3]}',
            ]
            for sys in (a, b):
                r = by_case[cid][sys]
                sel = [m for m in r["selection"]["selected_ids"] if not m.startswith("bg")]
                labels = {m["id"]: m["label"] for m in case["memories"]}
                ans = (r.get("answer") or {}).get("answer", {})
                lines.append(
                    f"- {sys}: selected {[f'{m}:{labels.get(m, "?")}' for m in sel]} "
                    f"(+{len(r['selection']['selected_ids']) - len(sel)} background) -> "
                    f'"{ans.get("final_answer", "")}"{" [abstain]" if ans.get("abstain") else ""}{" [conflict]" if ans.get("conflict") else ""}'
                )
    return "\n".join(lines)


def load_cases_index(paths: Sequence[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for p in paths:
        path = Path(p)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    c = json.loads(line)
                    index[c["case_id"]] = c
    return index


def write_report(
    run: Path, *, primary: tuple[str, str] = ("hybrid-jev", "embedding"), charts: bool = True
) -> Path:
    metrics, manifest, rows, relations = _load(run)
    cases = load_cases_index(manifest["run"]["cases_paths"])
    systems = [s for s in MAIN_SYSTEMS if s in metrics["overall"]]
    variants = [s for s in metrics["overall"] if s not in MAIN_SYSTEMS]
    calib_md, calib = calibration_table(rows, cases, relations)
    parts = [
        f"# Benchmark report: `{run.name}`",
        "",
        f"- Cases: {manifest['cases']} ({', '.join(Path(p).name for p in manifest['run']['cases_paths'])}); "
        f"background distractors per case: {manifest['run']['n_background']}; context budget: {manifest['run']['budget']} tokens",
        f"- Git commit: `{manifest['git_commit']}`{' (dirty)' if manifest['git_dirty'] else ''}; question schema `{manifest['question_schema_version']}`; "
        f"policy `{manifest['policy_version']}`; answer prompt `{manifest['answer_prompt_version']}`",
        f"- Models observed: {manifest['models_observed']}; embedding `{manifest['models']['embedding']}`; reranker `{manifest['models']['reranker']}`",
        f"- Judge failures (cases): {manifest['judge_failures']}",
        "",
        "Intervals are 95% family-level bootstrap CIs. Latency is modelled from recorded per-call latencies "
        "(Qwen calls were recorded under benchmark concurrency, shared with answer generation).",
        "",
        "## Primary comparison (pre-registered)",
        "",
        primary_comparison(rows, *primary),
        "",
        "## All systems",
        "",
        summary_table(metrics, systems),
        "",
        "## Answer accuracy by category",
        "",
        category_table(metrics, "answer_correct", systems),
        "",
        "## Memory-selection accuracy by category",
        "",
        category_table(metrics, "selection_correct", systems),
    ]
    if variants:
        parts += [
            "",
            "## Secondary analyses (variants)",
            "",
            summary_table(metrics, sorted(variants)),
        ]
    if relations:
        parts += [
            "",
            "## Write-time lifecycle quality (gold pairs)",
            "",
            lifecycle_table(relations),
        ]
    parts += ["", "## Calibration of judge probabilities", "", calib_md]
    parts += [
        "",
        f"## Failure cases: {primary[0]} vs {primary[1]}",
        "",
        failure_buckets(rows, cases, *primary),
    ]
    if charts:
        chart_dir = run / "charts"
        chart_dir.mkdir(exist_ok=True)
        names = make_charts(metrics, calib, chart_dir, systems)
        parts += ["", "## Charts", ""] + [f"![{n}](charts/{n})" for n in names]
    out = run / "report.md"
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


def make_charts(
    metrics: dict[str, Any], calib: dict[str, Any], out_dir: Path, systems: Sequence[str]
) -> list[str]:
    from jevmem.benchmark.charts import bar_chart, reliability_chart, scatter_quality_latency

    overall = metrics["overall"]

    def rows_for(metric: str) -> list[tuple[str, float, float | None, float | None]]:
        data = [(s, overall[s][metric]) for s in systems if overall[s][metric]["mean"] is not None]
        data.sort(key=lambda kv: -kv[1]["mean"])
        return [(s, e["mean"], e["lo"], e["hi"]) for s, e in data]

    made = []
    bar_chart(
        rows_for("answer_correct"),
        title="Answer accuracy",
        subtitle="Same answer model, prompt and 1024-token budget for every system; bars 95% CI",
        out=out_dir / "answer_accuracy.png",
        xmax=110,
    )
    made.append("answer_accuracy.png")
    bar_chart(
        rows_for("forbidden_selected"),
        title="Stale or poisoned memories in context",
        subtitle="Share of cases whose context included a forbidden memory (lower is better)",
        out=out_dir / "forbidden_in_context.png",
    )
    made.append("forbidden_in_context.png")
    bar_chart(
        rows_for("context_tokens"),
        title="Memory context size",
        subtitle="Mean tokens of memory injected into the answer prompt",
        out=out_dir / "context_tokens.png",
        percent=False,
    )
    made.append("context_tokens.png")
    group = {"hybrid-jev": "jev", "embedding-jev": "jev", "bm25-jev": "jev", "hybrid-qwen": "qwen"}
    pts = [
        (
            s,
            overall[s]["end_to_end_ms"]["mean"],
            overall[s]["answer_correct"]["mean"],
            group.get(s, "baseline"),
        )
        for s in systems
        if overall[s]["end_to_end_ms"]["mean"] is not None
        and overall[s]["answer_correct"]["mean"] is not None
        and s != "recency"
    ]
    scatter_quality_latency(
        pts,
        title="Answer quality vs latency",
        subtitle="Recency omitted (far below the others)",
        out=out_dir / "quality_vs_latency.png",
    )
    made.append("quality_vs_latency.png")
    curves = {}
    for name, label in (
        ("hybrid-jev utility (case memories)", "Jev utility"),
        ("hybrid-qwen utility (case memories)", "Qwen utility"),
    ):
        res = calib.get(name)
        if res is not None and res.n:
            filled = [b for b in res.bins if b.count]
            curves[label] = (
                [b.mean_confidence for b in filled],
                [b.accuracy for b in filled],
                res.ece,
            )
    if curves:
        reliability_chart(
            curves,
            title="Utility calibration",
            subtitle="Case memories; gold = required memory",
            out=out_dir / "reliability_utility.png",
        )
        made.append("reliability_utility.png")
    return made


def _overall(run: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run / "metrics.json").read_text(encoding="utf-8"))["overall"]
    return data


def budget_sweep_chart(run: Path, out: Path, metric: str = "answer_correct") -> tuple[Path, str]:
    from jevmem.benchmark.charts import line_chart

    overall = _overall(run)
    budgets = sorted({int(s.split("@")[1]) for s in overall if "@" in s})
    series: dict[str, list[tuple[float, float]]] = {}
    lines = [
        "| System | " + " | ".join(str(b) for b in [*budgets, 1024]) + " |",
        "|" + "---|" * (len(budgets) + 2),
    ]
    for name in ("hybrid-jev", "hybrid-qwen", "embedding", "rerank"):
        points = [
            (b, overall[f"{name}@{b}"][metric]["mean"]) for b in budgets if f"{name}@{b}" in overall
        ]
        if name in overall:
            points.append((1024, overall[name][metric]["mean"]))
        if points:
            series[name] = [(float(x), float(y)) for x, y in points if y is not None]
            lines.append(f"| {name} | " + " | ".join(f"{y * 100:.1f}" for _, y in points) + " |")
    line_chart(
        series,
        title="Accuracy under a context budget",
        subtitle="Same systems, smaller memory budgets (tokens)",
        xlabel="Memory context budget (tokens)",
        ylabel="Answer accuracy (%)",
        out=out,
        xscale="log2",
        xticks=[*budgets, 1024],
    )
    return out, "\n".join(lines)


def saturation_chart(
    runs: dict[int, Path], out: Path, metric: str = "selection_correct"
) -> tuple[Path, str]:
    from jevmem.benchmark.charts import line_chart

    levels = sorted(runs)
    data = {n: _overall(runs[n]) for n in levels}
    series: dict[str, list[tuple[float, float]]] = {}
    lines = [
        "| System | " + " | ".join(str(n) for n in levels) + " |",
        "|" + "---|" * (len(levels) + 1),
    ]
    for name in ("hybrid-jev", "hybrid-qwen", "embedding", "rerank"):
        points = [(n, data[n][name][metric]["mean"]) for n in levels if name in data[n]]
        points = [(n, y) for n, y in points if y is not None]
        if points:
            series[name] = [(float(n), float(y)) for n, y in points]
            lines.append(f"| {name} | " + " | ".join(f"{y * 100:.1f}" for _, y in points) + " |")
    label = "Memory-selection accuracy" if metric == "selection_correct" else "Answer accuracy"
    line_chart(
        series,
        title=f"{label} vs stored distractors",
        subtitle="Stratified test subset; distractors interleaved on each case timeline",
        xlabel="Background distractor memories per case",
        ylabel=f"{label} (%)",
        out=out,
        xscale="symlog",
        xticks=levels,
    )
    return out, "\n".join(lines)


def ablation_chart(run: Path, out: Path) -> tuple[Path, str]:
    from jevmem.benchmark.charts import bar_chart

    overall = _overall(run)
    order = [
        "hybrid-jev~relevance-only",
        "hybrid-jev~+utility",
        "hybrid-jev~+supersession",
        "hybrid-jev~+contradiction",
        "hybrid-jev~+temporal (full)",
        "hybrid-jev~read-only",
        "embedding~lifecycle-only",
    ]
    rows = [
        (
            n,
            overall[n]["selection_correct"]["mean"],
            overall[n]["selection_correct"]["lo"],
            overall[n]["selection_correct"]["hi"],
        )
        for n in order
        if n in overall
    ]
    bar_chart(
        rows,
        title="Which judgment dimensions matter",
        subtitle="Memory-selection accuracy; policy replays over identical cached judgments",
        out=out,
        emphasis=("hybrid-jev~+temporal (full)",),
        xmax=110,
    )
    table = ["| Variant | Selection acc. | Answer acc. | Forbidden in ctx |", "|---|---|---|---|"]
    for n in order:
        if n in overall:
            o = overall[n]
            table.append(
                f"| {n} | {_est(o['selection_correct']).fmt()} | {_est(o['answer_correct']).fmt()} | {_est(o['forbidden_selected']).fmt()} |"
            )
    return out, "\n".join(table)
