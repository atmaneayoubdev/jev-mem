# Lessons

Rules learned from corrections and surprises on this project. Review at session start.

- The Qwen endpoint sits behind Cloudflare, which blocks Python-urllib's User-Agent (403, "error code: 1010"). Always send an explicit User-Agent.
- Jev noul answers carry no `confidence`; only choice/score do. Never write policy code that reads `confidence` from a noul.
- Jev reads dates as text. All date ordering/arithmetic happens in Python; Jev only sees labels like `earlier_memory` / `later_memory`.
- Before trusting any category-level benchmark number, read per-case traces. A 0% category in the first smoke run turned out to be an answer-prompt artifact (the agent abstained because it "cannot search for gyms") even though retrieval was perfect.
- Ruff autofix can rewrite readable code (SIM905 exploded a stopword string into a 1,100-char list). Check what `--fix` changed before committing.
- Model-facing prompts must be validated with real calls, not only fakes. The extraction prompt returned `{"memories": []}` for every turn when its instructions were in the system message. Unit tests with a scripted generator passed; only the e2e track exposed it. Every prompt now has a live test (`pytest -m live`).
- Never split JSONL with `str.splitlines()`. It also splits on U+2028/U+0085, which JSON allows raw inside strings (LongMemEval has them). Iterate the file handle instead.
- When the user gives a budget in loose units ("10k cases"), work out the resource they are actually constrained by (here, Qwen wall-clock minutes). Size the job to that, state the reading in one line, and run it. Don't keep asking which unit they meant.
