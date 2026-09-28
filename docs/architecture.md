# Architecture

JevMem keeps four concerns strictly separate:

| Layer | Responsibility | Code |
|---|---|---|
| Retrieval | Find plausible candidates cheaply (BM25, dense, recency, hybrid union) | `retrieval/` |
| Judgment | Ask Jev typed questions about a candidate, a pair, or a query | `judgment/`, `providers/jev.py` |
| Policy | Turn probabilities into decisions and lifecycle links, deterministically | `policy/` |
| Generation | Answer the user with the selected memories (Qwen) | `providers/qwen.py`, `memory/service.py` |

**No LLM decides the memory lifecycle.** Qwen may *propose* memories during extraction. Only the write-time pipeline, meaning judge probabilities passed through `WritePolicy`, can create lineage links or supersede anything.

## Write path

```
POST /memories  or  chat extraction (Qwen proposes)
        │
        ▼
MemoryService.add_memory ── per-user lock, observation order enforced (409 if older)
        │
        ▼
LifecyclePipeline.write
  1. neighbours = earlier memories by dense document similarity ≥ 0.40
     (BM25 when no embedder): up to 5 active, then 2 superseded
  2. store + index the memory
  3. Jev (concurrently):
       profile(memory)         → durability (lasting | temporary | event),
                                 horizon (days | weeks | months | year),
                                 instruction-like? (injection check)
       pair(earlier, later)    → supersedes | contradicts | duplicate | refines | unrelated
  4. WritePolicy → status + links
       supersedes (confident)          → earlier SUPERSEDED (+ its duplicate cluster)
       supersedes by a temporary memory → TEMPORARILY_OVERRIDES (lapses with it)
       contradicts → CONFLICTS_WITH     duplicate → REINFORCES     refines → REFINES
       low confidence → UNCERTAIN_RELATION ("possibly outdated" at read time)
       instruction-like new memory → no links at all
  5. judge failure → lifecycle_pending=True (re-judged later), nothing faked
```

## Read path

```
query ──┬── retriever (mode) ─────────────┐
        └── Jev intent (current | historical | both), concurrently
                                          ▼
        one-hop lineage expansion: successors, conflict partners, overrides,
        predecessors (historical intent)
                                          ▼
        candidate facts in Python: validity at `now` (current / superseded / expired /
        overridden), conflict partners, possibly-outdated, instruction-like
                                          ▼
        Jev per candidate: relevance, utility (state = query + memory + memory_status label)
                                          ▼
        ReadPolicy, applied in order:
          archived / instruction-like → DROP
          relevance < τr − δ          → DROP
          non-current & intent=current → STALE (historical intent: eligible, annotated)
          relevant conflict partner   → CONFLICT (both injected, flagged)
          relevance ≥ τr & utility ≥ τu → USE
          inside the δ band           → UNCERTAIN (not injected by default)
          otherwise relevant          → KEEP (not injected)
                                          ▼
        ContextBuilder: token budget, duplicate dedupe, supersession chains rendered as one
        timeline, conflict pairs as one unit, provenance kept per item
                                          ▼
        Qwen answer
```

Modes (`recency`, `bm25`, `embedding`) skip judgment and inject top-K straight through the same context builder. `jev` uses BM25 candidates. `hybrid` uses the union of BM25 and dense top-P plus the 5 most recent memories.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Jev not configured, erroring or rate limited | Retries with backoff honouring `retry-after` (429/529/5xx). A circuit breaker opens after repeated failures and fails fast. Recall falls back to retriever order (`UNJUDGED`), with `judge_used=false` and `fallback_reason`. Writes are stored with `lifecycle_pending`. |
| Qwen unavailable | Clean 503 `service_unavailable`. JevMem never silently switches to another model. |
| Malformed provider output | `ResponseFormatError`, handled as a failure (never guessed around). |
| Out-of-order write | 409 `out_of_order` (the lifecycle compares only against earlier memories). |

## Observability

- Structured JSON logs carry `request_id`, `conversation_id` and `user_id` from context variables. Memory text and secrets are never logged.
- `/api/v1/metrics/summary` reports counters: recalls per mode, candidate, judged and selected counts, Jev requests, fallbacks, lifecycle judge calls, pending writes, extraction counts.
- It also reports latency summaries (retrieval, judge, generation, lifecycle writes) and per-client stats (requests, retries, errors, status codes, cache hits).
- `/api/v1/health` reports configuration and circuit-breaker state.

## Reproducibility

- **Response cache.** Every model call can be cached under a content hash of (provider, full request). The request includes the pinned model id. The cache stores the model id the server reported and the latency originally measured.
- **Replay.** Benchmark runs replay fully offline (`--replay`), and the manifest records the git commit, versions, hashes and observed model ids.
- **Latency is modelled.** It is computed from recorded per-call latencies (makespan under the judge concurrency limit) rather than wall-clock, so it survives replay.

## Storage

- **Stores.** `InMemoryStore` is used by the benchmark, with one per case. `SqlMemoryStore` (SQLAlchemy 2; SQLite by default, PostgreSQL via `DATABASE_URL` plus the `postgres` extra) is used by the app. Both implement the same `MemoryStore` protocol.
- **Search index.** The BM25 and dense index is in-process and rebuilt from the database the first time each user is accessed. A multi-process deployment would need a shared index; that is out of scope for v1.
