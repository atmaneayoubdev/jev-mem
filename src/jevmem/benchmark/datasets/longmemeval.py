"""LongMemEval (Wu et al., 2024; MIT license) → JevMem cases.

Source: `xiaowu0162/longmemeval-cleaned`, file `longmemeval_s_cleaned.json` (downloaded to
data/external/, never committed). Pre-registered subsets: `knowledge-update` and the
`single-session-user` control. `temporal-reasoning` is excluded because this pipeline does
no date arithmetic.

Mapping:
- memory unit = one user turn (the lifecycle and retrieval text), observed at its session's
  date, ordered by (date, session index, turn index);
- `now` = `question_date`; each instance is its own cluster for the bootstrap;
- labels: turns with `has_answer` in the *latest* evidence session are required; for
  knowledge-update, `has_answer` turns in earlier evidence sessions hold the outdated value
  and are labelled forbidden (stale); everything else is neutral;
- answers are graded with LongMemEval's official judge prompts (see `grading.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jevmem.benchmark.datasets.schema import Case, CaseMemory, ExpectedAnswer

DATASET = "longmemeval-s"
PREREGISTERED = ("knowledge-update", "single-session-user")
MAX_CHARS = 2000  # long pasted turns are truncated so judge states stay bounded


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def load_instances(path: Path, types: Iterable[str] = PREREGISTERED) -> list[dict[str, Any]]:
    wanted = set(types)
    with path.open(encoding="utf-8") as fh:
        data: list[dict[str, Any]] = json.load(fh)
    return [d for d in data if d["question_type"] in wanted]


def to_case(inst: dict[str, Any]) -> Case:
    sessions = list(
        zip(
            inst["haystack_session_ids"],
            inst["haystack_dates"],
            inst["haystack_sessions"],
            strict=True,
        )
    )
    answer_sessions = set(inst["answer_session_ids"])
    evidence_dates = sorted(parse_date(d) for sid, d, _ in sessions if sid in answer_sessions)
    latest = evidence_dates[-1] if evidence_dates else None
    task = inst["question_type"]
    abstention = inst["question_id"].endswith("_abs")

    memories: list[CaseMemory] = []
    for s_idx, (sid, date, turns) in enumerate(sessions):
        observed = parse_date(date)
        for t_idx, turn in enumerate(turns):
            if turn["role"] != "user" or not turn["content"].strip():
                continue
            label = "neutral"
            if turn.get("has_answer") and sid in answer_sessions:
                if observed == latest:
                    label = "required"
                elif task == "knowledge-update":
                    label = "forbidden"
            memories.append(
                CaseMemory(
                    id=f"s{s_idx:03d}t{t_idx:02d}",
                    content=turn["content"].strip()[:MAX_CHARS],
                    observed_at=observed,
                    sequence=s_idx * 1000 + t_idx,
                    label=label,
                )
            )
    category = task + ("_abs" if abstention else "")
    return Case(
        case_id=f"lme/{inst['question_id']}",
        dataset=DATASET,
        split="test",
        category=category,
        family=f"lme/{inst['question_id']}",
        user_id=f"lme/{inst['question_id']}",
        now=parse_date(inst["question_date"]),
        memories=memories,
        query=inst["question"],
        intent="current",
        expected=ExpectedAnswer(
            mode="llm_judge", reference=str(inst["answer"]), task=task, abstention=abstention
        ),
        background_eligible=False,
    )


def prepare(
    source: Path, out: Path, types: Iterable[str] = PREREGISTERED, limit: int | None = None
) -> int:
    instances = load_instances(source, types)
    if limit is not None:
        instances = instances[:limit]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for inst in instances:
            fh.write(to_case(inst).model_dump_json() + "\n")
    return len(instances)
