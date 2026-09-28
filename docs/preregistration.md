# Pre-registration (M1 test run)

**Status: DRAFT. Finalised and committed before the test families are written.** The commit hash of the final version is recorded in every test-run manifest.

## Primary comparison (the only confirmatory claim)

> **hybrid-jev** vs **embedding-lifecycle** (dense retrieval plus the heuristic "newest wins within near-duplicate clusters" lifecycle): end-to-end **answer accuracy** at an equal context budget (1024 tokens), on the synthetic **test** split, with 100 background distractors per case.

- **Statistic:** the difference in case-weighted mean accuracy, hybrid-jev minus embedding-lifecycle.
- **Uncertainty:** a paired family-level bootstrap (5,000 resamples), reported as a 95% CI.
- **Decision rule:** hybrid-jev is reported as better only if the CI's lower bound is above 0. If the CI contains 0, the result is reported as "no detectable difference". If the upper bound is below 0, hybrid-jev is reported as worse.

**Why this baseline:** embedding-lifecycle is the strongest *cheap* heuristic for the thesis: it resolves updates without any judge. Beating plain top-K similarity would not be informative, because it has no lifecycle mechanism at all.

## Secondary analyses (exploratory, reported without claims)

- The primary metric for every other system, and for each category.
- Memory-selection accuracy, forbidden-memory inclusion and context tokens.
- hybrid-jev vs hybrid-qwen (Jev vs the generative model as judge): accuracy, calibration (ECE, reliability diagrams), latency and cost.
- Ablations over judgment dimensions and pool size, replayed from cached judgments.
- The saturation sweep (0 / 10 / 100 / 1000 distractors).
- Lifecycle quality: supersession and contradiction precision/recall, false supersession, neighbour recall.
- The leakage probe (calib → test).
- LongMemEval: knowledge-update and single-session-user subsets only, run once, never tuned on.

## Frozen before test

- Question schema: `QUESTION_SCHEMA_VERSION`.
- Qwen-judge prompt: `PROMPT_VERSION`.
- Answer prompt: `ANSWER_PROMPT_VERSION`.
- Calibrated parameters: `benchmarks/params/calibrated-v1.json`.
- Policy version, the system list and the metrics code.

## Exclusions

- Cases where a judge failed (the judged system has no output) are excluded from that system's metrics and counted in the report.
- No other exclusions. No test case is dropped or edited after results are seen. Any test-set labelling error found afterwards is reported, and the result is re-run both with and without the fix.
