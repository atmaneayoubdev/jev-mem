"""Human-readable summaries of a run (markdown). Charts are produced separately."""

from __future__ import annotations

from typing import Any

from jevmem.benchmark.stats import Estimate

HEADLINE = [
    ("answer_correct", "Answer acc.", True),
    ("selection_correct", "Selection acc.", True),
    ("forbidden_selected", "Forbidden in ctx", True),
    ("neutral_selected", "Neutral in ctx", False),
    ("context_tokens", "Ctx tokens", False),
    ("judge_ms", "Judge ms", False),
    ("end_to_end_ms", "E2E ms", False),
]


def _est(raw: dict[str, Any]) -> Estimate:
    return Estimate.model_validate(raw)


def summary_table(metrics: dict[str, Any], systems: list[str] | None = None) -> str:
    overall = metrics["overall"]
    names = systems or list(overall)
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


def category_table(metrics: dict[str, Any], metric: str = "answer_correct") -> str:
    by_cat = metrics["by_category"]
    systems = sorted({s for cat in by_cat.values() for s in cat})
    lines = ["| Category | " + " | ".join(systems) + " |", "|" + "---|" * (len(systems) + 1)]
    for cat, rows in by_cat.items():
        cells = [_est(rows[s][metric]).fmt(digits=0) if s in rows else "-" for s in systems]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
