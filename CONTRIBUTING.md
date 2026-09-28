# Contributing

Thanks for helping. JevMem is a research project first, so changes that affect results carry an integrity burden, described below.

## Setup

```bash
uv sync --extra bench            # add --extra embeddings for the dense baseline (large download)
cp .env.example .env             # only needed for live tests and real runs
(cd frontend && npm install)
```

## Checks (all must pass)

```bash
uv run pytest                    # offline: fakes and mock transports, no API keys needed
uv run pytest -m live            # optional: real Jev/Qwen calls (needs keys)
uv run ruff check . && uv run ruff format --check .
uv run mypy
(cd frontend && npm run build && npm test)
```

## Ground rules

- **Keep layers separate.** Retrieval finds candidates, judges return probabilities, policies decide, and generation answers. No model may change lifecycle state directly.
- **Python owns time.** Never ask Jev to compare dates or compute durations.
- **Questions are generic and versioned.** Any wording change in `judgment/questions.py` bumps `QUESTION_SCHEMA_VERSION` and gets an entry in `docs/methodology.md` saying what it fixed on **dev**.
- **Never tune on test.** Iterate wording on dev and calibrate thresholds on calib (`jevmem benchmark calibrate`). A change that alters test results needs a new pre-registration and a new test split, not a re-run until it wins.
- **Report what you measure.** Benchmark numbers in docs must come from committed run directories that include raw per-case data. Losses and failure cases are published too.
- **Protect secrets.** Keys stay in `.env`. Tests must not require them unless marked `live`.

## Commits and pull requests

Keep commits small and focused. Explain *why* in the message. Include before/after metrics for changes that affect behaviour, together with the run ids.
