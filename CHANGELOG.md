# Changelog

## 0.1.0: first public research release

### Research core (M1)
- **Jev integration** through the TypeSafe System One API via OpenRouter.
  - Typed noul, choice and score questions and answers.
  - Pinned dated snapshot `typesafe/jev-1.13-20260917`.
  - Retries, single-flight deduplication, circuit breaker and response cache.
- **Question schema `q1.2`:** durability, horizon, injection check, pairwise relation, query intent, relevance, utility. States never contain dates.
- **Write-time lifecycle:** supersession (including across duplicate clusters), temporary overrides, contradictions, refinements, uncertain relations, pending re-judge.
- **Deterministic `WritePolicy` / `ReadPolicy`** (`p1.2`): USE / KEEP / DROP / STALE / CONFLICT / UNCERTAIN / UNJUDGED, with centralised calibrated thresholds.
- **Shared token-budgeted context builder:** chain timelines, conflict units, duplicate dedupe, provenance.
- **Retrieval:** BM25, dense (Qwen3-Embedding), recency, hybrid union, cross-encoder rerank, one-hop lineage expansion.
- **Qwen-as-judge baseline** with logprob-derived probabilities.
- **Benchmark:**
  - synthetic dev / calib / test (660 cases, 11 categories, family-level splits, independently authored test)
  - LongMemEval_S track
  - 12 systems; calibration on calib; family-level bootstrap
  - leakage probe, ablations, budget, saturation and pool sweeps, nondeterminism check, calibration/ECE
  - reports and charts with reproducibility manifests
- **Pre-registered test result:** hybrid-jev 91.7% vs dense top-10 80.1% answer accuracy (+11.6 pp [+5.1, +19.2]). Qwen-as-judge ties Jev (90.7%). See `benchmarks/results/M1-SUMMARY.md`.

### Application (M2)
- SQLAlchemy store (SQLite by default, PostgreSQL-ready), conversation turns with recall debug payloads.
- `MemoryService`: all five retrieval modes, chat with Qwen, propose-only memory extraction, compare, lineage, archive (never delete).
- FastAPI v1: chat, memories, retrieve, judge, compare, conversations, demo, benchmark, health, config, metrics.
- Request ids, CORS, size limits, rate-limit hook, safe errors, production mode.
- Provider error bodies are redacted (URLs, key and workspace ids) before logging; clients only see
  `<provider> <ErrorType> (HTTP n)`. Auth and quota failures open the circuit breaker at once.
- CLI: `doctor`, `serve`, `memory add/list`, `demo seed/reset`, and the `benchmark` commands.
- The Alex demo scenario.

### Demo UI (M3)
- React + Vite memory inspector: chat with per-turn judgments, retrieval-mode toggle, vector-vs-JevMem compare view, lineage timeline, benchmark table.

### Packaging (M4)
- Dockerfile (UI build + runtime, non-root, healthcheck) and docker-compose, with an optional PostgreSQL profile.
- Documentation: architecture, memory model, Jev design, benchmark, methodology, pre-registration, security, contributing.
