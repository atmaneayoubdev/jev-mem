# Benchmark report: `test-saturation-1000`

- Cases: 44 (test.jsonl); background distractors per case: 1000; context budget: 1024 tokens
- Git commit: `4a78c8ce52a83382765b1068009c0a144635e505` (dirty); question schema `q1.2`; policy `p1.2`; answer prompt `a1.1`
- Models observed: {'jev': ['typesafe/jev-1.13-20260917'], 'qwen': ['qwen3.8-27b']}; embedding `Qwen/Qwen3-Embedding-0.6B`; reranker `BAAI/bge-reranker-v2-m3`
- Judge failures (cases): {'jev': 0, 'qwen': 0}

Intervals are 95% family-level bootstrap CIs. Latency is modelled from recorded per-call latencies (Qwen calls were recorded under benchmark concurrency, shared with answer generation).

## Primary comparison (pre-registered)

Answer accuracy, hybrid-jev minus embedding: **+11.4 pp** [95% CI +2.3, +20.5] over 44 families (paired family bootstrap, 5,000 resamples) -> **hybrid-jev is better** (95% CI lower bound > 0).

## All systems

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| hybrid-jev | 86.4 [75.0, 95.5] | 84.1 [72.7, 93.2] | 4.5 [0.0, 11.4] | 2 [1, 2] | 80 [62, 103] | 2331 [2177, 2503] | 3609 [3410, 3850] | 0 |
| hybrid-qwen | 84.1 [72.7, 93.2] | 84.1 [72.7, 93.2] | 0.0 | 0 [0, 1] | 45 [34, 60] | 3982 [3783, 4179] | 5324 [5084, 5603] | 0 |
| embedding | 75.0 [61.4, 86.4] | 54.5 [40.9, 68.2] | 29.5 [15.9, 43.2] | 9 [9, 9] | 232 [228, 237] | 0 | 1154 [1100, 1212] | 0 |
| rerank | 72.7 [59.1, 86.4] | 54.5 [40.9, 68.2] | 31.8 [18.2, 45.5] | 9 [9, 9] | 231 [227, 235] | 0 | 1411 [1201, 1783] | 0 |

## Answer accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 75 [25, 100] | 100 | 75 [25, 100] | 75 [25, 100] |
| adversarial | 100 | 100 | 50 [0, 100] | 50 [0, 100] |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 75 [25, 100] |
| implicit_update | 100 | 100 | 100 | 100 |
| lexically_distant | 25 [0, 75] | 0 | 25 [0, 75] | 25 [0, 75] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 50 [0, 100] | 50 [0, 100] | 25 [0, 75] | 25 [0, 75] |
| supersession | 100 | 100 | 100 | 75 [25, 100] |
| temporary_state | 100 | 100 | 50 [0, 100] | 75 [25, 100] |

## Memory-selection accuracy by category

| Category | hybrid-jev | hybrid-qwen | embedding | rerank |
|---|---|---|---|---|
| abstention | 100 | 100 | 100 | 100 |
| adversarial | 75 [25, 100] | 100 | 0 | 0 |
| coexistence | 100 | 75 [25, 100] | 100 | 100 |
| contradiction | 100 | 100 | 100 | 100 |
| historical | 100 | 100 | 100 | 100 |
| implicit_update | 100 | 100 | 0 | 0 |
| lexically_distant | 25 [0, 75] | 0 | 25 [0, 75] | 25 [0, 75] |
| plain_recall | 100 | 100 | 100 | 100 |
| similar_useless | 50 [0, 100] | 50 [0, 100] | 25 [0, 75] | 25 [0, 75] |
| supersession | 100 | 100 | 0 | 0 |
| temporary_state | 75 [25, 100] | 100 | 50 [0, 100] | 50 [0, 100] |

## Secondary analyses (variants)

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| hybrid-jev#pool10 | 84.1 [72.7, 93.2] | 81.8 [70.5, 93.2] | 4.5 [0.0, 11.4] | 1 [1, 2] | 72 [58, 89] | 1800 [1713, 1903] | 3102 [2947, 3299] | 0 |
| hybrid-jev#pool20 | 86.4 [75.0, 95.5] | 84.1 [72.7, 93.2] | 4.5 [0.0, 11.4] | 2 [1, 2] | 80 [62, 103] | 2331 [2177, 2503] | 3609 [3410, 3850] | 0 |
| hybrid-jev#pool5 | 84.1 [72.7, 93.2] | 81.8 [70.5, 93.2] | 4.5 [0.0, 11.4] | 1 [1, 1] | 60 [51, 71] | 1454 [1351, 1571] | 2771 [2612, 2964] | 0 |
| hybrid-jev#pool50 | 88.6 [77.3, 97.7] | 86.4 [75.0, 95.5] | 4.5 [0.0, 11.4] | 2 [1, 3] | 91 [66, 128] | 3592 [3397, 3828] | 4869 [4618, 5183] | 0 |

## Write-time lifecycle quality (gold pairs)

| Judge | Supersession P | Supersession R | Contradiction P | Contradiction R | False supersession | Neighbour recall |
|---|---|---|---|---|---|---|
| jev | 1.00 | 0.88 | 1.00 | 1.00 | 0.00 (0/4) | 1.00 (22/22) |
| qwen | 1.00 | 1.00 | 1.00 | 0.75 | 0.00 (0/4) | 1.00 (22/22) |

## Calibration of judge probabilities

| Probabilities | n | ECE | Brier |
|---|---|---|---|
| hybrid-jev utility (all candidates) | 1509 | 0.117 | 0.041 |
| hybrid-jev utility (case memories) | 95 | 0.247 | 0.161 |
| hybrid-qwen utility (all candidates) | 1590 | 0.016 | 0.014 |
| hybrid-qwen utility (case memories) | 95 | 0.136 | 0.115 |
| jev relation (top-choice) | 26 | 0.100 | 0.098 |
| qwen relation (top-choice) | 26 | 0.067 | 0.025 |

## Failure cases: hybrid-jev vs embedding

| Bucket | Cases |
|---|---|
| hybrid-jev right, embedding wrong | 5 |
| embedding right, hybrid-jev wrong | 0 |
| both wrong | 6 |
| both right | 33 |

#### hybrid-jev right, embedding wrong

**temporary_state/t-pharmacy-refit-expired/i0** (temporary_state). Query: "Which pharmacy should my next repeat prescription be sent to?". Expected: value ['CVS']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "CVS near my flat"
- embedding: selected ['m1:required', 'm2:forbidden'] (+8 background) -> "Boots"

**temporary_state/t-antibiotic-course-active/i0** (temporary_state). Query: "What should I keep in mind before having wine with dinner tonight?". Expected: value ['tinidazole', 'antibiotic*', 'no alcohol']
- hybrid-jev: selected ['m2:required', 'm1:neutral'] (+0 background) -> "Avoid alcohol due to tinidazole"
- embedding: selected ['m1:neutral'] (+9 background) -> "Riesling"

**similar_useless/t-supplement-anticoagulant/i0** (similar_useless). Query: "I'm thinking of starting fish oil supplements; what should I take into account?". Expected: value ['rivaroxaban', 'your blood thinner*', 'your blood-thinner*']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Rivaroxaban interaction"
- embedding: selected ['m2:neutral'] (+9 background) -> "Traditional medicine history"

#### embedding right, hybrid-jev wrong
_none_

#### both wrong

**similar_useless/t-party-quiet-hours/i0** (similar_useless). Query: "I'm throwing Rafael's birthday party at my flat next Wednesday night; what should I take into account?". Expected: value ['9pm', 'quiet hour*', 'quiet-hour*']
- hybrid-jev: selected ['m2:neutral'] (+0 background) -> "Party-planning ideas from blogs"
- embedding: selected ['m2:neutral'] (+9 background) -> "Party planning ideas from blogs"

**similar_useless/t-suit-nickel/i0** (similar_useless). Query: "I'm having a suit made for my brother's wedding; what should I tell the tailor to keep in mind?". Expected: value ['nickel', 'allerg*']
- hybrid-jev: selected [] (+6 background) -> "Loose, flowing fabrics that move with the body"
- embedding: selected [] (+10 background) -> "Well-tailored blazer"

**lexically_distant/t-race-fuelling-diabetes/i0** (lexically_distant). Query: "What health factor should shape my fuelling plan for the marathon?". Expected: value ['diabet*', 'insulin', 'type 1']
- hybrid-jev: selected [] (+0 background) -> "Insufficient information" [abstain]
- embedding: selected ['m2:neutral'] (+9 background) -> "Energy gel every five kilometres"
