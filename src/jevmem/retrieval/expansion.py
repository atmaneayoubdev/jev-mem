"""Deterministic one-hop link expansion after candidate retrieval.

Write-time lifecycle links let the read path recover memories that retrieval missed:
if an old AWS preference is retrieved but the Azure memory that superseded it is not
(lexically distant), the successor is added. Conflict partners and temporary overrides
are added in both directions; predecessors are added only for historical/both intent.
"""

from __future__ import annotations

from collections.abc import Sequence

from jevmem.memory.lineage import conflict_partners, supersession_chain
from jevmem.memory.models import LinkType, Memory, MemoryStatus
from jevmem.memory.store import MemoryStore
from jevmem.retrieval.base import MemoryCandidate


def expand_candidates(
    candidates: Sequence[MemoryCandidate],
    store: MemoryStore,
    intent: str,
    *,
    max_added: int = 10,
) -> list[MemoryCandidate]:
    out = list(candidates)
    present = {c.memory.id for c in candidates}
    added = 0

    def add(memory: Memory, source: str) -> None:
        nonlocal added
        if memory.id in present or added >= max_added or memory.status is MemoryStatus.ARCHIVED:
            return
        present.add(memory.id)
        out.append(MemoryCandidate(memory=memory, score=0.0, rank=len(out), sources=[source]))
        added += 1

    for cand in candidates:
        mid = cand.memory.id
        chain = supersession_chain(store, mid)
        position = next(i for i, m in enumerate(chain) if m.id == mid)
        for later in chain[position + 1 :]:
            add(later, "link:successor")
        if intent in ("historical", "both"):
            for earlier in reversed(chain[:position]):
                add(earlier, "link:predecessor")
        for partner in conflict_partners(store, mid):
            add(partner, "link:conflict")
        for link in store.links_to(mid, [LinkType.TEMPORARILY_OVERRIDES]):
            add(store.get(link.source_id), "link:override")
        for link in store.links_from(mid, [LinkType.TEMPORARILY_OVERRIDES]):
            add(store.get(link.target_id), "link:override")
    return out
