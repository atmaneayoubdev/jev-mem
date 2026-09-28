"""Shared background history (distractors).

A fixed pool of ordinary user memories on topics disjoint from every benchmark case,
generated once with the Qwen provider, keyword-filtered against case vocabulary, and
committed as a static JSONL artifact (so no model call is needed to reproduce a run).

Each background memory has a fixed relative position r in (0, 1). In a case spanning
[start, now), it is observed at start + r * (now - start): distractors interleave with
the case memories (Recency gets no free win), their relative order is identical in
every case, and the file order defines nested saturation levels (level N = first N).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel

from jevmem.benchmark.datasets.schema import Case, CaseMemory
from jevmem.benchmark.datasets.synthetic import vocab
from jevmem.providers.qwen import GenerationProvider

TOPICS = [
    "novels and books they have read",
    "favourite films",
    "TV series they watch",
    "board games",
    "video games",
    "gardening",
    "houseplants",
    "baking bread and cakes",
    "painting and drawing",
    "photography",
    "learning a foreign language",
    "chess",
    "podcasts they enjoy",
    "museum visits",
    "jigsaw puzzles",
    "knitting and crochet",
    "woodworking projects",
    "astronomy and stargazing",
    "birdwatching",
    "volunteering",
    "home decoration",
    "childhood memories",
    "favourite colours and styles",
    "household chores and routines",
    "furniture they own",
    "crossword puzzles",
    "collecting stamps or coins",
    "poetry",
    "theatre and musicals",
    "concerts they attended",
    "history topics they find interesting",
    "science documentaries",
    "kitchen gadgets",
    "sewing",
    "pottery",
    "calligraphy",
    "origami",
    "camping",
    "model trains and miniatures",
    "philosophy books",
    "space exploration news",
    "fountain pens and stationery",
    "tabletop role-playing games",
    "opera and ballet",
    "journaling",
]

# Case topics that must never appear in background memories. Whole words (plural allowed);
# a trailing `*` marks a prefix. Every slot value in `vocab` is also blocked as a phrase.
_BLOCKED_WORDS = """
cloud aws azure server deploy* car cars drive driving phone iphone live lived moved moving
apartment city bank salary account gym membership coffee tea latte espresso airline* flight*
fly flying seat window aisle hotel* doctor dentist gp clinic blood allerg* vegan* vegetarian*
meat steak shellfish peanut* nut nuts diet birthday sister brother daughter son partner wife
husband kid kids child children dog cat rabbit parrot tortoise pet pets laptop editor code
coding programming job work working office employer company colleague* teammate* wheelchair
knee music streaming subscription conference trip travel* weekend parents restaurant* dinner
snack* budget saving deposit resort venue shift hospital sport tennis padel swimming climbing
cycling running yoga appointment* email vpn toyota kia honda ford tesla mazda hyundai
volkswagen subaru nissan samsung google oracle apple microsoft amazon
"""


def _blocked_pattern() -> re.Pattern[str]:
    alternatives: set[str] = set()
    for word in _BLOCKED_WORDS.split():
        if word.endswith("*"):
            alternatives.add(re.escape(word[:-1]) + r"[a-z]*")
        else:
            alternatives.add(re.escape(word) + r"(?:s|es)?")
    for name in dir(vocab):
        values = getattr(vocab, name)
        if isinstance(values, list):
            alternatives.update(re.escape(str(v).lower()) for v in values)
    ordered = sorted(alternatives, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(ordered) + r")(?![a-z0-9])", re.I)


BLOCKED = _blocked_pattern()


class BackgroundMemory(BaseModel):
    id: str
    content: str
    position: float  # relative position in (0, 1)
    topic: str


async def generate_pool(
    provider: GenerationProvider, *, per_topic: int = 30, seed: int = 7
) -> list[BackgroundMemory]:
    schema = {
        "type": "object",
        "properties": {"statements": {"type": "array", "items": {"type": "string"}}},
        "required": ["statements"],
    }

    async def one(topic: str) -> list[str]:
        prompt = (
            f"Write {per_topic} different short first-person statements that a person might tell "
            f"a personal assistant about their {topic}. Each must be one natural sentence with a "
            "specific detail. Do not mention travel, work, family members, pets, food, drink, "
            "health, money, technology products, or places they live. Return JSON."
        )
        result = await provider.complete(
            [{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.8,
            json_schema=schema,
        )
        return [str(s) for s in json.loads(result.text).get("statements", [])]

    batches = await asyncio.gather(*(one(topic) for topic in TOPICS))
    pool: list[tuple[str, str]] = []
    seen: set[str] = set()
    for topic, statements in zip(TOPICS, batches, strict=True):
        for statement in statements:
            text = " ".join(statement.split())
            key = text.lower()
            if 15 <= len(text) <= 200 and key not in seen and not BLOCKED.search(text):
                seen.add(key)
                pool.append((topic, text))
    rng = random.Random(seed)
    rng.shuffle(pool)
    return [
        BackgroundMemory(
            id=f"bg{i:04d}", content=text, position=round(rng.uniform(0.02, 0.98), 6), topic=topic
        )
        for i, (topic, text) in enumerate(pool)
    ]


def save_pool(pool: Sequence[BackgroundMemory], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for item in pool:
            fh.write(item.model_dump_json() + "\n")


def load_pool(path: Path) -> list[BackgroundMemory]:
    with path.open(encoding="utf-8") as fh:
        return [BackgroundMemory.model_validate_json(line) for line in fh if line.strip()]


def with_background(case: Case, pool: Sequence[BackgroundMemory], n: int) -> list[CaseMemory]:
    """Case memories plus the first `n` background memories placed on the case timeline."""
    if not case.background_eligible or n <= 0:
        return list(case.memories)
    start = min(m.observed_at for m in case.memories)
    span = case.now - start
    extra = [
        CaseMemory(
            id=bg.id,
            content=bg.content,
            observed_at=start + timedelta(seconds=span.total_seconds() * bg.position),
            sequence=1000 + i,
            label="neutral",
        )
        for i, bg in enumerate(pool[:n])
    ]
    return sorted([*case.memories, *extra], key=lambda m: (m.observed_at, m.sequence))
