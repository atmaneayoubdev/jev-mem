"""End-to-end track: raw user turns -> Qwen extraction -> the normal pipeline.

Each case memory (and each background distractor) is replayed as a user turn. Qwen's
propose-only extractor turns it into zero or more memories, which inherit the gold label of
the turn they came from. The transformed case then runs through exactly the same lifecycle,
recall, context and answer code as the memory-given track, so the difference between the
two tracks measures what extraction loses or distorts.

Gold write-time relations are not carried over (one turn can yield several memories), so the
e2e track reports answer and selection metrics only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import timedelta

from pydantic import BaseModel

from jevmem.benchmark.datasets.background import BackgroundMemory, with_background
from jevmem.benchmark.datasets.schema import Case, CaseMemory
from jevmem.memory.extraction import extract_memories
from jevmem.providers.errors import ProviderError
from jevmem.providers.qwen import GenerationProvider


class ExtractionStats(BaseModel):
    turns: int = 0
    memories: int = 0
    empty_turns: int = 0
    failed_turns: int = 0
    required_turns_lost: int = 0  # required turns that produced no memory at all


async def extract_case(
    case: Case,
    background: Sequence[BackgroundMemory],
    n_background: int,
    generator: GenerationProvider,
    stats: ExtractionStats,
) -> Case:
    turns = with_background(case, background, n_background)

    async def one(turn: CaseMemory) -> tuple[CaseMemory, list[str]]:
        try:
            proposals = await extract_memories(generator, turn.content)
        except ProviderError:
            stats.failed_turns += 1
            return turn, []
        return turn, [p.content for p in proposals]

    results = await asyncio.gather(*(one(t) for t in turns))
    memories: list[CaseMemory] = []
    for turn, contents in results:
        stats.turns += 1
        if not contents:
            stats.empty_turns += 1
            if turn.label == "required":
                stats.required_turns_lost += 1
        for i, content in enumerate(contents):
            memories.append(
                CaseMemory(
                    id=f"{turn.id}-x{i}",
                    content=content,
                    observed_at=turn.observed_at + timedelta(seconds=i),
                    sequence=turn.sequence,
                    label=turn.label,
                )
            )
        stats.memories += len(contents)
    return case.model_copy(
        update={
            "case_id": f"e2e/{case.case_id}",
            "dataset": f"{case.dataset}+e2e",
            "memories": memories,
            "relations": [],
            "background_eligible": False,
        }
    )


async def extract_cases(
    cases: Sequence[Case],
    background: Sequence[BackgroundMemory],
    n_background: int,
    generator: GenerationProvider,
    concurrency: int = 8,
) -> tuple[list[Case], ExtractionStats]:
    stats = ExtractionStats()
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> Case:
        async with semaphore:
            return await extract_case(case, background, n_background, generator, stats)

    return list(await asyncio.gather(*(one(c) for c in cases))), stats
