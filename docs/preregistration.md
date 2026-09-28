# Pre-registration (M1 test run)

**Status: FINAL.** This version was committed in the same commit that froze the question schema. That was before any test family existed, and git history shows the test families were added afterwards. Every test-run manifest records the commit hash.

## What was frozen

| Item | Value |
|---|---|
| Question schema | `q1.2` (`src/jevmem/judgment/questions.py`) |
| Qwen-judge prompt | `qp1.0` |
| Answer prompt | `a1.1` |
| Policy | `p1.2` |
| Calibrated parameters | `benchmarks/params/calibrated-v1.json` (fit on calib only) |
| Background pool | `benchmarks/datasets/background-v1.jsonl`; main run uses N=100 per case |
| Context budget | 1024 tokens (main) |
| Jev model | `typesafe/jev-1.13-20260917` via OpenRouter |
| Qwen model | `qwen3.8-27b`; thinking off for judging and answering |
| Embeddings / reranker | `Qwen/Qwen3-Embedding-0.6B` / `BAAI/bge-reranker-v2-m3` |

## Primary comparison (the only confirmatory claim)

> **hybrid-jev** vs **embedding** (dense top-K, K=10 as calibrated): end-to-end **answer accuracy** on the synthetic **test** split, with 100 background distractors per case and a 1024-token context budget.

- **How the comparator was chosen:** by a rule fixed before test existed. It is the baseline with the highest answer accuracy on calib under calibrated parameters. `embedding` and `embedding-lifecycle` tied at 100.0%, and the simpler system was chosen.
  - The draft pre-registration had named `embedding-lifecycle`. The calib results showed plain dense top-K is at least as strong, so a heuristic-lifecycle comparator would have been a weaker baseline.
- **Statistic:** the difference in case-weighted mean accuracy, hybrid-jev minus embedding.
- **Uncertainty:** a paired family-level bootstrap (5,000 resamples), reported as a 95% CI.
- **Decision rule:**
  - Lower CI bound above 0: hybrid-jev is better.
  - Upper CI bound below 0: hybrid-jev is worse.
  - Otherwise: "no detectable difference".

**Expected outcome, stated in advance:** calib answer accuracy was already at or near ceiling for dense top-10 (100.0) and hybrid-jev (97.0). "No detectable difference" in answer accuracy is therefore a likely and acceptable result. The calib data suggest JevMem's measured advantages lie in selection precision and context size, which is why those are pre-registered as secondary analyses below.

## Secondary analyses (pre-specified, exploratory, no confirmatory claims)

1. **Selection:** memory-selection accuracy, forbidden-memory (stale or poisoned) inclusion rate and context tokens, for every system.
2. **Context-budget sweep:** answer accuracy at budgets of **128, 256 and 512** tokens for embedding, rerank, hybrid-jev and hybrid-qwen. Tests whether selection quality matters when context is scarce.
3. **Saturation sweep:** 0, 10, 100 and 1000 background distractors, on a stratified test subset of 4 families per category, 1 instance each.
4. **Judge comparison:** hybrid-jev vs hybrid-qwen on accuracy, latency and cost. It also covers calibration of utility and relation probabilities (ECE, reliability curves) against gold labels.
5. **Ablations,** replayed from cached judgments with no new judge calls:
   - relevance only
   - plus utility
   - plus supersession
   - plus contradiction
   - plus temporal validity (full)
   - write-time lifecycle only vs read-time judgment only
   - candidate pool size 5, 10, 20, 50 at 1000 distractors
6. **Lifecycle quality:** supersession and contradiction precision/recall against gold pairs, the false-supersession rate from the coexistence category, and write-time neighbour recall.
7. **Leakage probe:** bag-of-words logistic regression trained on calib and evaluated on test.
8. **Nondeterminism:** Jev judgments for 50 test cases repeated without the cache; decision flip rate.
9. **LongMemEval:** knowledge-update and single-session-user subsets, run once with the frozen configuration and never tuned on.

## Exclusions and changes

- If a judge fails on a case, that case is excluded from that judged system's metrics and counted in the report. No other exclusions.
- No test case is edited or dropped after results are seen. If a test labelling error is found later, it is reported, and results are shown both with and without the correction.
- Any deviation from this document is reported in the results as a deviation.
