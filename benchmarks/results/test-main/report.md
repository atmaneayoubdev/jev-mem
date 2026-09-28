# Benchmark report: `test-main`

- Cases: 396 (test.jsonl); background distractors per case: 100; context budget: 1024 tokens
- Git commit: `a5850b1fef341162926c2143e6259a97086ad244` (dirty); question schema `q1.2`; policy `p1.2`; answer prompt `a1.1`
- Models observed: {'jev': ['typesafe/jev-1.13-20260917'], 'qwen': ['qwen3.8-27b'], 'jev-readonly': ['typesafe/jev-1.13-20260917']}; embedding `Qwen/Qwen3-Embedding-0.6B`; reranker `BAAI/bge-reranker-v2-m3`
- Judge failures (cases): {'jev': 0, 'qwen': 0}

Intervals are 95% family-level bootstrap CIs. Latency is modelled from recorded per-call latencies (Qwen calls were recorded under benchmark concurrency, shared with answer generation).

## Primary comparison (pre-registered)

Answer accuracy, hybrid-jev minus embedding: **+11.6 pp** [95% CI +5.1, +19.2] over 66 families (paired family bootstrap, 5,000 resamples) -> **hybrid-jev is better** (95% CI lower bound > 0).

## All systems

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| hybrid-jev | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [1, 1] | 60 [54, 66] | 1494 [1425, 1572] | 2773 [2699, 2852] | 0 |
| embedding-jev | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [1, 1] | 60 [54, 66] | 1385 [1319, 1459] | 2664 [2594, 2741] | 0 |
| bm25-jev | 76.8 [66.2, 85.9] | 75.3 [65.1, 84.8] | 3.0 [0.0, 7.6] | 0 [0, 1] | 46 [40, 51] | 1021 [951, 1098] | 2273 [2199, 2353] | 0 |
| hybrid-qwen | 90.7 [83.1, 96.7] | 90.4 [82.8, 96.7] | 0.3 [0.0, 0.8] | 0 [0, 0] | 44 [38, 50] | 3492 [3321, 3681] | 4778 [4605, 4965] | 0 |
| embedding | 80.1 [70.7, 88.4] | 60.6 [48.5, 71.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 235 [232, 237] | 0 | 1290 [1265, 1330] | 0 |
| embedding-threshold | 80.3 [71.5, 88.6] | 60.6 [49.0, 72.0] | 31.8 [21.2, 43.9] | 10 [8, 12] | 262 [217, 310] | 0 | 1294 [1269, 1333] | 0 |
| embedding-lifecycle | 80.1 [70.7, 88.4] | 60.6 [48.5, 71.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 235 [232, 237] | 0 | 1290 [1265, 1330] | 0 |
| embedding-decay | 76.3 [66.9, 84.8] | 57.6 [46.0, 68.7] | 29.5 [18.9, 40.9] | 7 [7, 7] | 192 [190, 195] | 0 | 1288 [1271, 1309] | 0 |
| rerank | 76.0 [66.2, 85.1] | 58.3 [46.2, 69.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 234 [231, 237] | 0 | 1358 [1323, 1417] | 0 |
| rerank-threshold | 78.5 [68.9, 86.9] | 61.4 [49.5, 72.2] | 31.8 [21.2, 43.9] | 45 [45, 45] | 1016 [1015, 1017] | 0 | 1376 [1327, 1444] | 0 |
| bm25 | 52.5 [40.9, 64.4] | 47.2 [35.9, 59.1] | 24.5 [14.1, 35.1] | 1 [1, 2] | 66 [61, 71] | 0 | 1249 [1225, 1288] | 0 |
| recency | 22.7 [12.1, 31.8] | 13.6 [6.1, 22.7] | 0.0 | 6 [6, 6] | 151 [150, 152] | 0 | 1295 [1266, 1336] | 0 |

## Answer accuracy by category

| Category | hybrid-jev | embedding-jev | bm25-jev | hybrid-qwen | embedding | embedding-threshold | embedding-lifecycle | embedding-decay | rerank | rerank-threshold | bm25 | recency |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| abstention | 83 [50, 100] | 83 [50, 100] | 83 [50, 100] | 100 | 58 [17, 100] | 61 [17, 94] | 58 [17, 100] | 67 [26, 97] | 50 [17, 83] | 44 [14, 81] | 61 [17, 94] | 100 |
| adversarial | 100 | 100 | 83 [50, 100] | 100 | 44 [14, 78] | 33 [0, 67] | 44 [14, 78] | 44 [14, 78] | 39 [8, 75] | 39 [8, 75] | 31 [0, 67] | 0 |
| coexistence | 94 [83, 100] | 94 [83, 100] | 94 [83, 100] | 83 [50, 100] | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 0 |
| contradiction | 100 | 100 | 100 | 100 | 92 [75, 100] | 97 [92, 100] | 92 [75, 100] | 100 | 94 [83, 100] | 92 [75, 100] | 50 [17, 83] | 100 |
| historical | 100 | 100 | 100 | 100 | 97 [92, 100] | 94 [83, 100] | 97 [92, 100] | 94 [83, 100] | 100 | 100 | 89 [67, 100] | 0 |
| implicit_update | 100 | 100 | 83 [50, 100] | 100 | 100 | 100 | 100 | 94 [83, 100] | 94 [89, 100] | 100 | 44 [11, 83] | 0 |
| lexically_distant | 67 [25, 100] | 67 [25, 100] | 0 | 50 [17, 83] | 61 [22, 94] | 67 [25, 100] | 61 [22, 94] | 25 [0, 58] | 42 [8, 83] | 53 [17, 86] | 0 | 0 |
| plain_recall | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 0 |
| similar_useless | 64 [17, 97] | 64 [17, 97] | 33 [0, 67] | 64 [17, 97] | 53 [17, 86] | 56 [17, 89] | 53 [17, 86] | 39 [6, 72] | 50 [17, 83] | 67 [25, 97] | 33 [0, 67] | 0 |
| supersession | 100 | 100 | 83 [50, 100] | 100 | 100 | 97 [92, 100] | 100 | 100 | 100 | 100 | 33 [0, 67] | 0 |
| temporary_state | 100 | 100 | 83 [50, 100] | 100 | 75 [46, 100] | 78 [56, 100] | 75 [46, 100] | 75 [42, 100] | 67 [33, 100] | 69 [35, 100] | 36 [3, 69] | 50 [17, 83] |

## Memory-selection accuracy by category

| Category | hybrid-jev | embedding-jev | bm25-jev | hybrid-qwen | embedding | embedding-threshold | embedding-lifecycle | embedding-decay | rerank | rerank-threshold | bm25 | recency |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| abstention | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| adversarial | 81 [47, 100] | 81 [47, 100] | 67 [25, 100] | 97 [92, 100] | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| coexistence | 94 [83, 100] | 94 [83, 100] | 94 [83, 100] | 83 [50, 100] | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 0 |
| contradiction | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 50 [17, 83] | 0 |
| historical | 100 | 100 | 100 | 100 | 97 [92, 100] | 94 [83, 100] | 97 [92, 100] | 94 [83, 100] | 100 | 100 | 89 [67, 100] | 0 |
| implicit_update | 100 | 100 | 83 [50, 100] | 100 | 0 | 0 | 0 | 0 | 0 | 0 | 17 [0, 50] | 0 |
| lexically_distant | 67 [25, 100] | 67 [25, 100] | 0 | 50 [17, 83] | 64 [23, 97] | 67 [25, 100] | 64 [23, 97] | 25 [0, 58] | 42 [8, 83] | 53 [17, 86] | 0 | 0 |
| plain_recall | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 0 |
| similar_useless | 64 [17, 97] | 64 [17, 97] | 33 [0, 67] | 64 [17, 97] | 56 [17, 89] | 56 [17, 89] | 56 [17, 89] | 39 [6, 72] | 50 [17, 83] | 72 [40, 97] | 33 [0, 67] | 0 |
| supersession | 100 | 100 | 83 [50, 100] | 100 | 0 | 0 | 0 | 17 [0, 50] | 0 | 0 | 14 [0, 42] | 0 |
| temporary_state | 83 [50, 100] | 83 [50, 100] | 67 [33, 100] | 100 | 50 [17, 83] | 50 [17, 83] | 50 [17, 83] | 58 [17, 92] | 50 [17, 83] | 50 [17, 83] | 17 [0, 50] | 50 [17, 83] |

## Secondary analyses (variants)

| System | Answer acc. | Selection acc. | Forbidden in ctx | Neutral in ctx | Ctx tokens | Judge ms | E2E ms | Failed |
|---|---|---|---|---|---|---|---|---|
| embedding@128 | 77.8 [67.9, 86.4] | 57.6 [45.5, 68.7] | 31.8 [21.2, 43.9] | 3 [3, 4] | 120 [119, 122] | 0 | 1287 [1271, 1308] | 0 |
| embedding@256 | 80.1 [70.7, 88.4] | 60.6 [48.5, 71.7] | 31.8 [21.2, 43.9] | 9 [8, 9] | 234 [231, 236] | 0 | 1290 [1265, 1329] | 0 |
| embedding@512 | 80.1 [70.7, 88.4] | 60.6 [48.5, 71.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 235 [232, 237] | 0 | 1290 [1265, 1330] | 0 |
| embedding~lifecycle-only | 83.3 [74.7, 90.4] | 83.3 [74.5, 91.2] | 1.8 [0.0, 5.1] | 9 [9, 9] | 234 [232, 237] | 0 | 1280 [1264, 1300] | 0 |
| hybrid-jev@128 | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [0, 1] | 59 [53, 64] | 1494 [1425, 1572] | 2773 [2699, 2852] | 0 |
| hybrid-jev@256 | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [1, 1] | 60 [54, 66] | 1494 [1425, 1572] | 2773 [2699, 2852] | 0 |
| hybrid-jev@512 | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [1, 1] | 60 [54, 66] | 1494 [1425, 1572] | 2773 [2699, 2852] | 0 |
| hybrid-jev~+contradiction | 90.9 [83.6, 96.7] | 88.9 [81.1, 95.2] | 4.8 [0.3, 10.6] | 1 [1, 1] | 61 [55, 67] | 1494 [1425, 1572] | 2772 [2699, 2852] | 0 |
| hybrid-jev~+supersession | 90.9 [83.6, 96.7] | 88.9 [81.1, 95.2] | 4.8 [0.3, 10.6] | 1 [1, 1] | 60 [54, 66] | 1494 [1425, 1572] | 2770 [2697, 2850] | 0 |
| hybrid-jev~+temporal (full) | 91.7 [84.6, 97.0] | 89.9 [81.8, 96.2] | 3.3 [0.0, 7.8] | 1 [1, 1] | 60 [54, 66] | 1494 [1425, 1572] | 2773 [2699, 2852] | 0 |
| hybrid-jev~+utility | 90.9 [83.6, 96.7] | 71.5 [61.1, 81.1] | 22.2 [13.1, 32.3] | 1 [1, 1] | 65 [59, 72] | 1494 [1425, 1572] | 2772 [2700, 2853] | 0 |
| hybrid-jev~read-only | 84.8 [76.0, 92.4] | 63.4 [51.5, 74.2] | 30.3 [19.7, 42.4] | 1 [1, 1] | 66 [60, 72] | 1544 [1458, 1639] | 2820 [2735, 2917] | 0 |
| hybrid-jev~relevance-only | 89.4 [81.8, 95.5] | 66.4 [54.5, 77.0] | 27.3 [16.7, 37.9] | 1 [1, 1] | 69 [62, 76] | 1494 [1425, 1572] | 2773 [2701, 2852] | 0 |
| hybrid-qwen@128 | 90.7 [83.1, 96.7] | 90.4 [82.8, 96.7] | 0.3 [0.0, 0.8] | 0 [0, 0] | 44 [38, 50] | 3492 [3321, 3681] | 4778 [4605, 4965] | 0 |
| hybrid-qwen@256 | 90.7 [83.1, 96.7] | 90.4 [82.8, 96.7] | 0.3 [0.0, 0.8] | 0 [0, 0] | 44 [38, 50] | 3492 [3321, 3681] | 4778 [4605, 4965] | 0 |
| hybrid-qwen@512 | 90.7 [83.1, 96.7] | 90.4 [82.8, 96.7] | 0.3 [0.0, 0.8] | 0 [0, 0] | 44 [38, 50] | 3492 [3321, 3681] | 4778 [4605, 4965] | 0 |
| rerank@128 | 76.3 [66.9, 85.1] | 57.6 [45.5, 68.7] | 31.8 [21.2, 43.9] | 3 [3, 4] | 121 [120, 122] | 0 | 1352 [1316, 1413] | 0 |
| rerank@256 | 76.0 [66.2, 85.1] | 58.3 [46.2, 69.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 234 [231, 236] | 0 | 1358 [1323, 1417] | 0 |
| rerank@512 | 76.0 [66.2, 85.1] | 58.3 [46.2, 69.7] | 31.8 [21.2, 43.9] | 9 [9, 9] | 234 [231, 237] | 0 | 1358 [1323, 1417] | 0 |

## Write-time lifecycle quality (gold pairs)

| Judge | Supersession P | Supersession R | Contradiction P | Contradiction R | False supersession | Neighbour recall |
|---|---|---|---|---|---|---|
| jev | 1.00 | 0.91 | 1.00 | 0.97 | 0.00 (0/36) | 0.99 (185/186) |
| qwen | 1.00 | 0.99 | 1.00 | 0.86 | 0.00 (0/36) | 0.99 (185/186) |

## Calibration of judge probabilities

| Probabilities | n | ECE | Brier |
|---|---|---|---|
| hybrid-jev utility (all candidates) | 9916 | 0.092 | 0.027 |
| hybrid-jev utility (case memories) | 932 | 0.253 | 0.164 |
| hybrid-qwen utility (all candidates) | 9917 | 0.015 | 0.013 |
| hybrid-qwen utility (case memories) | 933 | 0.135 | 0.115 |
| jev relation (top-choice) | 220 | 0.087 | 0.073 |
| qwen relation (top-choice) | 220 | 0.037 | 0.015 |

## Failure cases: hybrid-jev vs embedding

| Bucket | Cases |
|---|---|
| hybrid-jev right, embedding wrong | 49 |
| embedding right, hybrid-jev wrong | 3 |
| both wrong | 30 |
| both right | 314 |

#### hybrid-jev right, embedding wrong

**temporary_state/t-pharmacy-refit-expired/i1** (temporary_state). Query: "Which pharmacy should my next repeat prescription be sent to?". Expected: value ['Duane Reade']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Duane Reade"
- embedding: selected ['m1:required', 'm2:forbidden'] (+8 background) -> "Rowlands"

**temporary_state/t-exchange-partner-expired/i0** (temporary_state). Query: "Who am I meeting for Polish conversation practice this Thursday?". Expected: value ['Declan']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Declan"
- embedding: selected ['m1:required', 'm3:forbidden', 'm2:neutral'] (+7 background) -> "Leila"

**similar_useless/t-suit-nickel/i0** (similar_useless). Query: "I'm having a suit made for my brother's wedding; what should I tell the tailor to keep in mind?". Expected: value ['nickel', 'allerg*']
- hybrid-jev: selected ['m1:required'] (+0 background) -> "Nickel allergy; avoid metal buttons, buckles, and zips"
- embedding: selected [] (+10 background) -> "A well-tailored blazer makes me feel like myself"

#### embedding right, hybrid-jev wrong

**similar_useless/t-guitar-handedness/i1** (similar_useless). Query: "I'm buying my first electric guitar; what should I take into account?". Expected: value ['left-hand*', 'left hand*', 'lefty']
- hybrid-jev: selected [] (+0 background) -> "Budget, playing style, body shape, and neck profile"
- embedding: selected ['m2:neutral', 'm1:required'] (+8 background) -> "Left-handedness"

**coexistence/t-term-vs-holiday-childcare/i1** (coexistence). Query: "Where does Leo go on weekdays during the summer holidays?". Expected: value ['Starlight Club']
- hybrid-jev: selected ['m1:neutral'] (+0 background) -> "Treehouse Club"
- embedding: selected ['m2:required', 'm1:neutral'] (+8 background) -> "Starlight Club holiday camp"

#### both wrong

**similar_useless/t-party-quiet-hours/i0** (similar_useless). Query: "I'm throwing Rafael's birthday party at my flat next Wednesday night; what should I take into account?". Expected: value ['9pm', 'quiet hour*', 'quiet-hour*']
- hybrid-jev: selected ['m2:neutral'] (+0 background) -> "Party-planning ideas from blogs"
- embedding: selected ['m2:neutral'] (+9 background) -> "Party-planning ideas from blogs"

**similar_useless/t-suit-nickel/i3** (similar_useless). Query: "I'm having a suit made for a black-tie gala; what should I tell the tailor to keep in mind?". Expected: value ['nickel', 'allerg*']
- hybrid-jev: selected ['m2:neutral'] (+2 background) -> "Charcoal grey"
- embedding: selected [] (+10 background) -> "Charcoal grey"

**similar_useless/t-guitar-handedness/i0** (similar_useless). Query: "I'm buying my first acoustic guitar; what should I take into account?". Expected: value ['left-hand*', 'left hand*', 'lefty']
- hybrid-jev: selected ['m2:neutral'] (+1 background) -> "Cherry wood's reddish hue and Fender's manufacturing process"
- embedding: selected ['m2:neutral'] (+9 background) -> "Fender"
