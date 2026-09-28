# Benchmark

## Tracks

1. **Synthetic** (`benchmarks/datasets/synthetic-v1`).
   - **Categories (11):** supersession, implicit update (no cue words), temporary state, similar-but-useless, lexically distant but useful, contradiction, historical query (chains, reverts), abstention, coexistence control, adversarial poisoning, and plain-recall control.
   - **Size:** 132 dev + 132 calib + 396 test cases. Splits are made **by template family**.
   - **Test authoring:** test families were written after the freeze by an independent agent that could not see the questions Jev is asked.
   - **Distractors:** each case interleaves N background distractors from a shared 1,654-memory pool of hobby topics, keyword-filtered against every case topic. Every case carries its own simulated `now`.
2. **LongMemEval_S** (external). Pre-registered subsets: knowledge-update and single-session-user.
   - User turns are memories, stamped with session dates.
   - Scoring is against the *latest* evidence session; earlier knowledge-update evidence is labelled stale.
   - Graded with the official judge prompts on Qwen, so the numbers are not comparable to published GPT-4o-judged results.

## Gold labels

Each memory in a case is **required**, **forbidden** (stale, wrong, or poisoned) or **neutral**. Answers are checked deterministically: word-boundary alias matching on the agent's short `final_answer`, plus `abstain` and `conflict` flags for those categories.

## Systems (12)

All systems go through the same context builder, the same 1024-token budget, the same Qwen answer prompt (`a1.1`), and the same calibration objective. `recency`, `bm25`, `embedding` and `rerank` take their top-K; the rest:

| System | Selection |
|---|---|
| `embedding-threshold`, `rerank-threshold` | a calibrated score threshold |
| `embedding-decay` | dense score × 0.5^(age / half-life) |
| `embedding-lifecycle` | dense top-K; newest wins within near-duplicate clusters |
| `bm25-jev`, `embedding-jev`, `hybrid-jev` | first stage → Jev (write-time lifecycle + read-time judgment) → policy |
| `hybrid-qwen` | hybrid → Qwen-as-judge, doing the write and read steps with the same questions and policy |

## Metrics

- **Answer:** accuracy (headline); forbidden value used in the answer.
- **Selection:** accuracy (all required memories injected, no forbidden one); required recall; forbidden and neutral inclusion.
- **Ranking:** Recall@K, MRR, nDCG@10.
- **Recall stages:** first-stage recall and recall after link expansion.
- **Lifecycle:** relation precision/recall against gold pairs; false supersession; write-time neighbour recall; durability accuracy.
- **Calibration:** ECE, Brier, reliability bins.
- **Efficiency:** modelled latency, judge calls, tokens and cost; context tokens.
- **Uncertainty:** 95% family-level (cluster) bootstrap, and a paired bootstrap for comparisons.

## Commands

```bash
uv run jevmem benchmark generate [--splits dev,calib,test]
uv run jevmem benchmark generate-background          # regenerate distractor pool (committed already)
uv run jevmem benchmark calibrate --split calib
uv run jevmem benchmark run --run-id NAME --split test --params benchmarks/params/calibrated-v1.json \
    [--budgets 128,256,512] [--ablations] [--pools 5,10,20,50 --pool-max 50] \
    [--families-per-category 4 --instances-per-family 1] [--n-background 1000] [--replay]
uv run jevmem benchmark report --run-id NAME
uv run jevmem benchmark probe --train calib --evaluate test
uv run jevmem benchmark nondeterminism --split test --n 50
uv run jevmem benchmark lme-prepare && uv run jevmem benchmark run --run-id lme --cases data/external/longmemeval/cases-preregistered.jsonl --n-background 0 --supersede-mode annotate
```

## Where the results are

- `benchmarks/results/M1-SUMMARY.md`: every M1 result in one place.
- `benchmarks/results/<run>/`: `manifest.json`, `cases.jsonl` (raw per-case), `metrics.json`, `relations.jsonl`, `durability.jsonl`, `report.md`, `charts/`.
- `docs/methodology.md` and `docs/preregistration.md`: how tuning was kept away from test.
