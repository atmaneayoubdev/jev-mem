# JevMem — M1 (research core)

Full plan: `C:\Users\atman\.claude\plans\starry-squishing-crescent.md` (approved 2026-09-28).

## Checklist
- [x] 1. `.gitignore` first → git init; pyproject (cu128 torch index), config, logging, `.env.example`, `tasks/lessons.md`
- [x] 2. Memory models, store protocol + InMemoryStore, tests
- [x] 3. Jev + Qwen clients, cache, fakes; probe dated Jev id + Qwen logprobs; live validation; `jevmem doctor`
- [x] 4. Question schemas (Jev + Qwen), judgment service, Qwen judge
- [x] 5. Write + read policies with branch/boundary tests (chains, reverts, temp overrides, cluster propagation, conflict, low-conf intent)
- [x] 6. Retrievers + one-hop expansion + optional embedding/reranker (CUDA check, CPU fallback)
- [x] 7. Lifecycle pipeline + shared context builder
- [x] 8. Synthetic generator (dev + calib families only), distractor pool, review export
- [x] 9. Runner, systems registry, metrics, family bootstrap, leakage probe, ablation replays
- [x] 10. Dev question iteration (equal budget Jev/Qwen); calibrate all systems on calib; freeze + commit schemas; `docs/preregistration.md`
- [x] 11. Author test families (f7c79f3); test run + ablations + budget + saturation/pool + nondeterminism (947906e, 97dfb3a)
- [~] 12. LongMemEval loader, throughput measurement (10 inst: 12.7 min, ~1.2k Jev calls/inst), pre-registered subsets (running)
- [x] 13. Reports, charts, failure buckets, manifest; `benchmarks/results/M1-SUMMARY.md`
- [ ] 14. Check in with user

Gate after every step: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` → commit.

## Review
- Primary (pre-registered, test): hybrid-jev 91.7% vs dense top-10 80.1%, +11.6 pp [+5.1, +19.2].
- Qwen-as-judge in the same architecture ties Jev (+1.0 pp [-3.5, +5.6]) and is better calibrated; Jev is faster/cheaper per query.
- Gains concentrate in adversarial, abstention, expired temporary state; ties on supersession (the answer model resolves dated updates in context).
- Calib was also used for bug fixes (logged), so only test is held-out. LongMemEval running.

# M2 — application (autonomous per user, 2026-09-29)
- [x] SQLAlchemy store (SQLite default, PostgreSQL-ready) behind MemoryStore; conversations/turns
- [x] MemoryService: add/recall (all 5 modes)/archive/lineage; per-user index rebuilt from DB
- [x] Qwen memory extraction (structured, propose-only) + chat pipeline
- [x] Circuit breaker + service metrics
- [x] FastAPI: chat, memories CRUD (archive not delete), retrieve, judge, compare, lineage, benchmark, health, config, metrics, demo
- [x] Security: CORS, size limits, rate-limit hook, safe errors, request ids
- [x] CLI: serve, memory add/list, demo seed/reset; Alex demo seed
- [x] Tests (fakes, sqlite tmp) + live smoke
# M3 — React/Vite inspector, mode toggle, comparison view, lineage timeline
- [x] Chat & Inspector, Compare, Memories & Timeline, Benchmark views; 22 vitest tests (ec7afc7)
- [x] Served by FastAPI at `/`; verified live against the API with the Alex demo
# M4
- [x] README, docs (architecture, memory model, Jev design, benchmark), SECURITY, CONTRIBUTING, CHANGELOG
- [x] Dockerfile + compose; image builds (624 MB), container healthy, non-root, UI at `/`, `/api/v1/health` ok
- [x] Provider error bodies redacted (URLs, key/workspace ids) in logs and `jevmem doctor`
- [x] Fresh-clone test: installs, 135+ offline tests pass, datasets regenerate byte-identical
- [x] e2e track implemented; extraction bug found and fixed (x1.1)
- [x] Raw results gzipped
- [x] LongMemEval partial: first 82/148 (all cached) graded -> `lme-partial-82`; +2.4 pp [-2.4, +7.3], 149 vs 344 ctx tokens
- [x] Fix: JSONL readers split on U+2028 (report crashed on LME) (ba8a42a)
- [ ] BLOCKED (Jev key monthly limit reached): remaining 66 knowledge-update instances; re-run e2e Jev column
