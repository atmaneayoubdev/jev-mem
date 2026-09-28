# Methodology

This document records how the JevMem benchmark is built and run, including every change made during development, so readers can judge whether the results were tuned toward a conclusion.

## Question and hypothesis

Can a calibrated decision model (TypeSafe Jev), with a deterministic policy making the final decision, give better long-term agent memory than similarity-only retrieval? The design is set up so that Jev does **not** have to win: the baselines are tuned with the same objective, the primary comparison is pre-registered, and every result is published with its per-case data.

## Architecture under test

- **Write time.** Each new memory is compared with its nearest *earlier* memories: active ones first, then a few superseded ones. Neighbours come from BM25 plus dense document-document similarity above a floor. The judge answers two things. Its **durability** is lasting, temporary or event, and for temporary memories a **horizon** of days, weeks, months or year. Its **relation** to each neighbour is supersedes, contradicts, duplicate, refines or unrelated. The deterministic `WritePolicy` turns these into lineage links. Python computes all ordering and expiry, and Jev never compares dates.
- **Read time.** Candidates come from BM25, dense retrieval, recency or a hybrid of the three. Deterministic one-hop link expansion adds successors, conflict partners and overrides, plus predecessors when the query asks about the past. The judge scores query **intent** (current, historical or both) and each candidate's **relevance** and **utility**. The deterministic `ReadPolicy` returns USE, KEEP, DROP, STALE, CONFLICT or UNCERTAIN, and a shared token-budgeted context builder renders the result.
- **Generation.** Every system uses the same Qwen answer prompt. Only the memory context differs.

## Systems

Every system goes through the same context builder, token budget (1024) and answer prompt.

| System | Description |
|---|---|
| recency | Most recent K memories |
| bm25 | BM25 top-K |
| embedding | Dense top-K (Qwen3-Embedding) |
| embedding-threshold | Dense, cosine ≥ calibrated θ |
| embedding-decay | Dense score × 0.5^(age / half-life), top-K |
| embedding-lifecycle | Dense top-K; newest memory wins within near-duplicate clusters (heuristic lifecycle baseline) |
| rerank / rerank-threshold | Dense top-50 → bge-reranker-v2-m3, top-K or score ≥ θ |
| bm25-jev / embedding-jev / hybrid-jev | First stage → Jev (write-time lifecycle + read-time judgment) → policy |
| hybrid-qwen | Same as hybrid-jev, with Qwen as the judge for both write time and read time (same questions, its own calibrated thresholds, probabilities taken from token logprobs) |

## Datasets

### Synthetic (`benchmarks/datasets/synthetic-v1`)
- **Categories:** supersession, implicit update (no cue words), temporary state, similar-but-useless, lexically-distant-useful, contradiction, historical query, abstention, coexistence control, adversarial poisoning, and plain-recall control.
- **Structure:** each category has several template families, and each family has 6 seeded instances. Splits are made **by family**, so no template wording is shared between dev, calib and test.
- **Labels:** every memory is *required*, *forbidden* (stale, wrong or poisoned) or *neutral*. Labels are read only by the scorer.
- **Distractors:** a shared background history of 1,654 hobby memories. It was generated once with Qwen, keyword-filtered against every case topic, and committed. Each memory has a fixed relative position and is stretched across each case's own timeline, so distractors interleave with case memories and Recency gets no free win.
- **Time:** every case carries its own simulated `now`.

### LongMemEval (external)
- **Source:** `longmemeval_s_cleaned.json`. The pre-registered subsets are knowledge-update and, as a control, single-session-user.
- **Memory units:** each user turn is one memory, stamped with its session date.
- **Labels:** turns with `has_answer` in the latest evidence session are required. For knowledge-update, `has_answer` turns in *earlier* evidence sessions hold the outdated value and are marked stale. The raw data lists both sessions as evidence, so scoring against both would penalise exactly the behaviour under test.
- **Supersession mode:** "annotate". A turn holds several facts, so a superseded turn is flagged in context rather than withheld.
- **Grading:** answers are graded with LongMemEval's official judge prompts, run on Qwen instead of GPT-4o, so the numbers are **not comparable to published results**.
- **Excluded:** temporal-reasoning, because this pipeline does no date arithmetic.

## Metrics

- **Headline:** end-to-end answer accuracy at an equal token budget.
  - Synthetic cases are scored by deterministic alias matching on the agent's short `final_answer`, with abstain and conflict flags where the category needs them.
  - LongMemEval uses its official judge prompts.
- **Selection:** memory-selection accuracy (every required memory injected, no forbidden memory injected), required-memory recall, and forbidden and neutral inclusion.
- **Ranking:** Recall@K, MRR and nDCG@10 for systems that rank.
- **Recall stages:** first-stage recall and recall after link expansion.
- **Lifecycle:** relation accuracy against gold pairs, including "not paired" when neighbour search never compared the pair; durability accuracy; the false-supersession rate from the coexistence category.
- **Efficiency:** retrieval latency, and judge latency modelled from the recorded per-call latencies (reproducible under cache replay); judge tokens and `usage.cost`; context tokens.
- **Uncertainty:** 95% family-level (cluster) bootstrap CIs, and a paired bootstrap for system differences.

## Controls against tuning to the test set

1. The wording of the question schema and prompts was iterated **only on dev** (log below). Jev and the Qwen judge share the question text, and each got the same number of iterations.
2. Thresholds and baseline parameters were calibrated **only on calib**, with one objective for every system: selection accuracy, with ties broken by fewer context tokens.
3. The schema was frozen and committed **before** the test families were written, and git history shows the order.
4. A bag-of-words leakage probe is trained on calib and evaluated on test. If it matches the judged systems, the benchmark is measuring template artefacts.
5. The primary comparison is pre-registered in `docs/preregistration.md`.
6. Judge failures are flagged and excluded from judged-system metrics; they are never replaced with fabricated judgments.

## Dev iteration log

| Version | Change | Reason (observed on dev) |
|---|---|---|
| q1.0 / qp1.0 / a1.0 | Initial schema, Qwen-judge prompt and answer prompt | — |
| q1.1 | Added a `year` horizon. Candidate states now carry a Python-computed `memory_status` label with no dates. | A memory saying "saving … this year" was classed as a months horizon and expired after 120 days. On historical queries, a superseded memory's utility was judged low because the judge could not tell it was past context. |
| a1.1 | The agent is told it cannot browse, should answer with the fact the request depends on, and should abstain only when a fact about the user is missing. | The temporary-state category scored 0% for *every* system despite correct retrieval: the agent abstained on "recommend a gym near where I live". |
| gold fix | "Saving … this year" was relabelled lasting → temporary. | Gold labelling error found while inspecting traces. |
