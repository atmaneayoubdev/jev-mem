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
- [~] 11. Author test families (done, f7c79f3); run all systems + ablations + saturation + nondeterminism on test, once (running)
- [~] 12. LongMemEval loader, throughput measurement (10 inst: 12.7 min, ~1.2k Jev calls/inst), pre-registered subsets (running)
- [~] 13. Reports, charts, failure buckets, manifest (tooling done)
- [ ] 14. Check in with user

Gate after every step: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` → commit.

## Review
(filled in at the end of M1)
