"""Deterministic answer scoring against `ExpectedAnswer`.

The agent answers as JSON `{final_answer, abstain, conflict}`. Matching runs on the short
`final_answer` only, case-insensitively, on word boundaries, with a fixed alias table for
common alternative names (e.g. "GCP" for "Google Cloud").
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel

from jevmem.benchmark.datasets.schema import ExpectedAnswer

ALIASES: dict[str, list[str]] = {
    "AWS": ["Amazon Web Services"],
    "Azure": ["Microsoft Azure"],
    "Google Cloud": ["GCP", "Google Cloud Platform"],
    "Oracle Cloud": ["OCI", "Oracle Cloud Infrastructure"],
    "VS Code": ["Visual Studio Code", "VSCode"],
    "IntelliJ IDEA": ["IntelliJ"],
    "Toyota Corolla": ["Corolla"],
    "Kia Sportage": ["Sportage"],
    "Honda Civic": ["Civic"],
    "Ford Focus": ["Focus"],
    "Tesla Model 3": ["Model 3"],
    "Mazda CX-5": ["CX-5"],
    "Hyundai Tucson": ["Tucson"],
    "Volkswagen Golf": ["VW Golf"],
    "Subaru Outback": ["Outback"],
    "Nissan Leaf": ["Leaf"],
    "Galaxy S24": ["Samsung Galaxy S24", "S24"],
    "Pixel 8": ["Google Pixel 8"],
}


class AgentAnswer(BaseModel):
    final_answer: str = ""
    abstain: bool = False
    conflict: bool = False


class AnswerScore(BaseModel):
    correct: bool
    forbidden_used: bool
    matched: list[str]
    reason: str


def _variants(value: str) -> list[str]:
    return [value, *ALIASES.get(value, [])]


def _mentions(text: str, value: str) -> bool:
    """Word-boundary match (plural allowed). A trailing `*` marks a prefix ("accessib*")."""
    for variant in _variants(value):
        core = variant.rstrip("*").lower()
        pattern = r"(?<![a-z0-9])" + re.escape(core)
        if not variant.endswith("*"):
            pattern += r"(?:s|es)?(?![a-z0-9])"  # plural forms count ("peanut" ~ "peanuts")
        if re.search(pattern, text):
            return True
    return False


def _any(text: str, values: Iterable[str]) -> list[str]:
    return [v for v in values if _mentions(text, v)]


def score_answer(answer: AgentAnswer, expected: ExpectedAnswer) -> AnswerScore:
    text = answer.final_answer.lower()
    forbidden = _any(text, expected.forbidden)
    used = bool(forbidden) and not answer.abstain
    match expected.mode:
        case "abstain":
            return AnswerScore(
                correct=answer.abstain, forbidden_used=used, matched=[], reason="abstain expected"
            )
        case "conflict":
            named = _any(text, expected.aliases)
            all_named = bool(expected.aliases) and len(named) == len(expected.aliases)
            ok = answer.conflict or answer.abstain or all_named
            return AnswerScore(
                correct=ok, forbidden_used=used, matched=named, reason="conflict expected"
            )
        case "all":
            named = _any(text, expected.aliases)
            ok = not answer.abstain and len(named) == len(expected.aliases) and not forbidden
            return AnswerScore(
                correct=ok, forbidden_used=used, matched=named, reason="all values expected"
            )
        case _:
            named = _any(text, expected.aliases)
            ok = not answer.abstain and bool(named) and not forbidden
            return AnswerScore(
                correct=ok, forbidden_used=used, matched=named, reason="value expected"
            )
