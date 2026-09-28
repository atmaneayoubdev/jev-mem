# Benchmark report: `test-saturation-10`

- Cases: 44 (test.jsonl); background distractors per case: 10; context budget: 1024 tokens
- Git commit: `4a78c8ce52a83382765b1068009c0a144635e505` (dirty); question schema `q1.2`; policy `p1.2`; answer prompt `a1.1`
- Models observed: {'jev': ['typesafe/jev-1.13-20260917'], 'qwen': ['qwen3.8-27b']}; embedding `Qwen/Qwen3-Embedding-0.6B`; reranker `BAAI/bge-reranker-v2-m3`
- Judge failures (cases): {'jev': 0, 'qwen': 0}

Intervals are 95% family-level bootstrap CIs. Latency is modelled from recorded per-call latencies (Qwen calls were recorded under benchmark concurrency, shared with answer generation).

## Primary comparison (pre-registered)

Answer accuracy, hybrid-jev minus embedding: **+6.8 pp** [95% CI +0.0, +15.9] over 44 families (paired family bootstrap, 5,000 resamples) -> **no detectable difference** (95% CI contains 0).

## All systems

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| hybrid-jev | 97.7 [93.2, 100.0] | 95.5 [88.6, 100.0] | 4.5 [0.0, 11.4] | 1 [0, 1] | 61 [55, 68] | 1094 [993, 1206] | 2712 [2254, 3522] | 0 |
| hybrid-qwen | 95.5 [88.6, 100.0] | 95.5 [88.6, 100.0] | 0.0 | 0 [0, 0] | 44 [37, 51] | 3340 [2652, 4157] | 4999 [4107, 6132] | 0 |
| embedding | 90.9 [81.8, 97.7] | 68.2 [54.5, 81.8] | 31.8 [18.2, 45.5] | 9 [8, 9] | 234 [231, 237] | 0 | 1549 [1220, 2185] | 0 |
| rerank | 81.8 [70.5, 93.2] | 61.4 [47.7, 75.0] | 31.8 [18.2, 45.5] | 9 [8, 9] | 236 [232, 239] | 0 | 1716 [1235, 2660] | 0 |

## Answer accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 75 [25, 100] | 100 | 75 [25, 100] | 75 [25, 100] |
| adversarial | 100 | 100 | 50 [0, 100] | 50 [0, 100] |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 100 |
| implicit_update | 100 | 100 | 100 | 75 [25, 100] |
| lexically_distant | 100 | 75 [25, 100] | 100 | 50 [0, 100] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 100 | 100 | 100 | 75 [25, 100] |
| supersession | 100 | 100 | 100 | 100 |
| temporary_state | 100 | 100 | 75 [25, 100] | 75 [25, 100] |

## Memory-selection accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 100 | 100 | 100 | 100 |
| adversarial | 75 [25, 100] | 100 | 0 | 0 |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 100 |
| implicit_update | 100 | 100 | 0 | 0 |
| lexically_distant | 100 | 75 [25, 100] | 100 | 50 [0, 100] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 100 | 100 | 100 | 75 [25, 100] |
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
| hybrid-jev utility (all candidates) | 548 | 0.096 | 0.038 |
| hybrid-jev utility (case memories) | 108 | 0.250 | 0.161 |
| hybrid-qwen utility (all candidates) | 548 | 0.024 | 0.020 |
| hybrid-qwen utility (case memories) | 108 | 0.117 | 0.096 |
| jev relation (top-choice) | 26 | 0.100 | 0.098 |
| qwen relation (top-choice) | 26 | 0.067 | 0.025 |

## Failure cases: hybrid-jev vs embedding

| Bucket | Cases |
|---|---|
| hybrid-jev right, embedding wrong | 3 |
| embedding right, hybrid-jev wrong | 0 |
| both wrong | 1 |
| both right | 40 |

#### hybrid-jev right, embedding wrong

**temporary_state/t-pharmacy-refit-expired/i0** (temporary_state). Query: "Which pharmacy should my next repeat prescription be sent to?". Expected: value ['CVS']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "CVS near my flat"
- embedding: selected ['m1:required', 'm2:forbidden'] (+8 background) -> "Boots"

**adversarial/t-forwarded-accountant-email/i0** (adversarial). Query: "Who should I send this year's receipts to for my tax return?". Expected: value ['Carrow']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Carrow Accounting"
- embedding: selected ['m1:required', 'm2:forbidden'] (+8 background) -> "Brightline"

**adversarial/t-subtle-note-vet/i0** (adversarial). Query: "Which vet practice should I take Juniper to for her annual booster?". Expected: value ['Parkside']
- hybrid-jev: selected ['m2:forbidden', 'm3:required'] (+0 background) -> "Parkside Vets" [conflict]
- embedding: selected ['m1:forbidden', 'm3:required', 'm2:forbidden'] (+7 background) -> "Willow Tree" [conflict]

#### embedding right, hybrid-jev wrong
_none_

#### both wrong

**abstention/t-tailor-name/i0** (abstention). Query: "What's my tailor's name?". Expected: abstain []
- hybrid-jev: selected ['m2:neutral', 'm1:neutral'] (+0 background) -> "Adeyemi" [conflict]
- embedding: selected ['m1:neutral', 'm2:neutral'] (+8 background) -> "Adeyemi"
