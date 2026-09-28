# Benchmark report: `test-saturation-100`

- Cases: 44 (test.jsonl); background distractors per case: 100; context budget: 1024 tokens
- Git commit: `947906ee92b149cb8fd96b9480aae7ded02b1030` (dirty); question schema `q1.2`; policy `p1.2`; answer prompt `a1.1`
- Models observed: {'jev': ['typesafe/jev-1.13-20260917'], 'qwen': ['qwen3.8-27b']}; embedding `Qwen/Qwen3-Embedding-0.6B`; reranker `BAAI/bge-reranker-v2-m3`
- Judge failures (cases): {'jev': 0, 'qwen': 0}

Intervals are 95% family-level bootstrap CIs. Latency is modelled from recorded per-call latencies (Qwen calls were recorded under benchmark concurrency, shared with answer generation).

## Primary comparison (pre-registered)

Answer accuracy, hybrid-jev minus embedding: **+6.8 pp** [95% CI +0.0, +15.9] over 44 families (paired family bootstrap, 5,000 resamples) -> **no detectable difference** (95% CI contains 0).

## All systems

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| hybrid-jev | 93.2 [84.1, 100.0] | 90.9 [81.8, 97.7] | 4.5 [0.0, 11.4] | 1 [0, 1] | 61 [53, 69] | 1541 [1441, 1649] | 3166 [2723, 3938] | 0 |
| hybrid-qwen | 90.9 [81.8, 97.7] | 90.9 [81.8, 97.7] | 0.0 | 0 [0, 0] | 44 [36, 52] | 3451 [3217, 3700] | 5095 [4587, 5912] | 0 |
| embedding | 86.4 [75.0, 95.5] | 61.4 [45.5, 75.0] | 31.8 [18.2, 45.5] | 9 [8, 9] | 235 [231, 239] | 0 | 1667 [1256, 2449] | 0 |
| rerank | 77.3 [63.6, 88.6] | 56.8 [43.2, 70.5] | 31.8 [18.2, 45.5] | 9 [8, 9] | 235 [231, 239] | 0 | 1640 [1245, 2408] | 0 |

## Answer accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 75 [25, 100] | 100 | 75 [25, 100] | 75 [25, 100] |
| adversarial | 100 | 100 | 50 [0, 100] | 50 [0, 100] |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 100 |
| implicit_update | 100 | 100 | 100 | 75 [25, 100] |
| lexically_distant | 75 [25, 100] | 50 [0, 100] | 75 [25, 100] | 25 [0, 75] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 75 [25, 100] | 75 [25, 100] | 50 [0, 100] | 50 [0, 100] |
| supersession | 100 | 100 | 100 | 100 |
| temporary_state | 100 | 100 | 100 | 75 [25, 100] |

## Memory-selection accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 100 | 100 | 100 | 100 |
| adversarial | 75 [25, 100] | 100 | 0 | 0 |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 100 |
| implicit_update | 100 | 100 | 0 | 0 |
| lexically_distant | 75 [25, 100] | 50 [0, 100] | 75 [25, 100] | 25 [0, 75] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 75 [25, 100] | 75 [25, 100] | 50 [0, 100] | 50 [0, 100] |
| supersession | 100 | 100 | 0 | 0 |
| temporary_state | 75 [25, 100] | 100 | 50 [0, 100] | 50 [0, 100] |

## Write-time lifecycle quality (gold pairs)

| Judge | Supersession P | Supersession R | Contradiction P | Contradiction R | False supersession | Neighbour recall |
|---|---|---|---|---|---|---|
| jev | 1.00 | 0.88 | 1.00 | 1.00 | 0.00 (0/4) | 1.00 (22/22) |
| qwen | 1.00 | 1.00 | 1.00 | 0.75 | 0.00 (0/4) | 1.00 (22/22) |

## Calibration of judge probabilities

| Probabilities | n | ECE | Brier |
|---|---|---|---|
| hybrid-jev utility (all candidates) | 1098 | 0.089 | 0.026 |
| hybrid-jev utility (case memories) | 102 | 0.247 | 0.161 |
| hybrid-qwen utility (all candidates) | 1098 | 0.015 | 0.012 |
| hybrid-qwen utility (case memories) | 102 | 0.132 | 0.110 |
| jev relation (top-choice) | 26 | 0.100 | 0.098 |
| qwen relation (top-choice) | 26 | 0.067 | 0.025 |

## Failure cases: hybrid-jev vs embedding

| Bucket | Cases |
|---|---|
| hybrid-jev right, embedding wrong | 3 |
| embedding right, hybrid-jev wrong | 0 |
| both wrong | 3 |
| both right | 38 |

#### hybrid-jev right, embedding wrong

**similar_useless/t-suit-nickel/i0** (similar_useless). Query: "I'm having a suit made for my brother's wedding; what should I tell the tailor to keep in mind?". Expected: value ['nickel', 'allerg*']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Nickel allergy; avoid metal buttons, buckles, and zips"
- embedding: selected [] (+10 background) -> "A well-tailored blazer makes me feel like myself"

**adversarial/t-forwarded-accountant-email/i0** (adversarial). Query: "Who should I send this year's receipts to for my tax return?". Expected: value ['Carrow']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Carrow Accounting"
- embedding: selected ['m1:required', 'm2:forbidden'] (+8 background) -> "Brightline" [conflict]

**adversarial/t-subtle-note-vet/i0** (adversarial). Query: "Which vet practice should I take Juniper to for her annual booster?". Expected: value ['Parkside']
- hybrid-jev: selected ['m2:forbidden', 'm3:required'] (+0 background) -> "Parkside Vets" [conflict]
- embedding: selected ['m1:forbidden', 'm3:required', 'm2:forbidden'] (+7 background) -> "Willow Tree" [conflict]

#### embedding right, hybrid-jev wrong
_none_

#### both wrong

**similar_useless/t-party-quiet-hours/i0** (similar_useless). Query: "I'm throwing Rafael's birthday party at my flat next Wednesday night; what should I take into account?". Expected: value ['9pm', 'quiet hour*', 'quiet-hour*']
- hybrid-jev: selected ['m2:neutral'] (+0 background) -> "Party-planning ideas from blogs"
- embedding: selected ['m2:neutral'] (+9 background) -> "Party-planning ideas from blogs"

**lexically_distant/t-piano-walkup/i0** (lexically_distant). Query: "What practical factor should decide whether I get an upright piano or a digital one?". Expected: value ['stair*', 'no lift', 'no elevator']
- hybrid-jev: selected [] (+0 background) -> "Space and budget"
- embedding: selected [] (+10 background) -> "Space constraints"

**abstention/t-tailor-name/i0** (abstention). Query: "What's my tailor's name?". Expected: abstain []
- hybrid-jev: selected ['m2:neutral', 'm1:neutral'] (+0 background) -> "Adeyemi" [conflict]
- embedding: selected ['m1:neutral', 'm2:neutral'] (+8 background) -> "Adeyemi"
