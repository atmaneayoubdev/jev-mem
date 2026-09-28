# JevMem — M1 (research core)

Full plan: `C:\Users\atman\.claude\plans\starry-squishing-crescent.md` (approved 2026-09-28).

## Checklist
- [ ] 1. `.gitignore` first → git init; pyproject (cu128 torch index), config, logging, `.env.example`, `tasks/lessons.md`
- [ ] 2. Memory models, store protocol + InMemoryStore, tests
- [ ] 3. Jev + Qwen clients, cache, fakes; probe dated Jev id + Qwen logprobs; live validation; `jevmem doctor`
- [ ] 4. Question schemas (Jev + Qwen), judgment service, Qwen judge
- [ ] 5. Write + read policies with branch/boundary tests (chains, reverts, temp overrides, cluster propagation, conflict, low-conf intent)
- [ ] 6. Retrievers + one-hop expansion + optional embedding/reranker (CUDA check, CPU fallback)
- [ ] 7. Lifecycle pipeline + shared context builder
- [ ] 8. Synthetic generator (dev + calib families only), distractor pool, review export
- [ ] 9. Runner, systems registry, metrics, family bootstrap, leakage probe, ablation replays
- [ ] 10. Dev question iteration (equal budget Jev/Qwen); calibrate all systems on calib; freeze + commit schemas; `docs/preregistration.md`
- [ ] 11. Author test families; run all systems + ablations + saturation + nondeterminism on test, once
- [ ] 12. LongMemEval loader, throughput measurement, pre-registered subsets
- [ ] 13. Reports, charts, failure buckets, manifest
- [ ] 14. Check in with user

Gate after every step: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` → commit.

## Review
(filled in at the end of M1)
