# Memory model

## Memory

| Field | Meaning |
|---|---|
| `id`, `user_id`, `session_id`, `source_turn_id` | identity and provenance |
| `content`, `normalized_content` | the memory text (one sentence in the user's voice when extracted) |
| `memory_type` | profile, preference, fact, goal, constraint, decision, event, relationship, work_context, temporary_state, other |
| `observed_at`, `sequence` | when it was said; the total order is `(observed_at, sequence, id)` |
| `created_at`, `valid_from`, `valid_until` | bookkeeping and an optional explicit validity window |
| `status` | `active`, `superseded` (durably replaced), or `archived` (removed by the user; kept for history) |
| `durability`, `horizon` | judged at write time: lasting / temporary / event; for temporary memories, days / weeks / months / year |
| `instruction_like` | judged at write time: the text tries to direct an AI (possible injection) |
| `lifecycle_pending` | lifecycle judgment failed; re-judge later |
| `confidence`, `tags`, `metadata` | optional; extraction stores `evidence` and a `temporary_hint` |

History is never deleted. `DELETE /memories/{id}` archives.

## Links (lineage)

Links run from the **later** memory (`source`) to the **earlier** one (`target`). Each link keeps the judge's probability distribution, its confidence, the judge id and model, and the schema and policy versions.

| Link | Created when | Effect |
|---|---|---|
| `supersedes` | later replaces earlier (confident) | earlier becomes `superseded`; so do its duplicates |
| `temporarily_overrides` | a *temporary* later memory replaces a lasting one | earlier is `overridden` while the later one is valid, then current again |
| `conflicts_with` | both cannot be true, with no indication of change | both are surfaced together and flagged |
| `reinforces` | same information | duplicates are deduplicated in context (the newest is kept) |
| `refines` | later adds detail; both remain true | none |
| `uncertain_relation` | the judge was not confident | "possibly outdated" note at read time |

Reverts work: A → B → A′. A′ supersedes B through its own active-neighbour pair. A′ is a duplicate of the superseded A, but it does **not** inherit A's superseded status.

## Validity at `now` (computed, never stored)

```
archived                                          → archived
status superseded                                 → superseded
valid_until ≤ now, or temporary and past its TTL  → expired
a valid temporary memory overrides it             → overridden
otherwise                                         → current
```

The TTL comes from the judged horizon: days = 7, weeks = 42, months = 180, year = 365. These values were set a priori from the horizon definitions and not fitted to data.

## Example lineage (the Alex demo)

```
Jan 06  "My preferred cloud provider is AWS…"              SUPERSEDED
          ↑ supersedes (p = 0.9x)
Aug 05  "Our company has started moving some services…"    SUPERSEDED
          ↑ supersedes
Sep 14  "We finished the migration… Azure is our preferred" ACTIVE, current

May 04  "I'm working from Riyadh for the next few weeks…"  ACTIVE, expired by late Sep
Feb 03  "My blood type is O negative."  ⟷ conflicts_with ⟷  Aug 19 "My blood type is A positive."
```

## Extraction

After each chat turn, Qwen proposes durable memories from the user's message as JSON (content, type, a temporary hint, evidence). Each proposal goes through the write-time lifecycle like any other memory. Qwen cannot mark anything superseded or deleted.
