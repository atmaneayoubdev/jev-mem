# Lessons

Rules learned from corrections and surprises on this project. Review at session start.

- The Qwen endpoint sits behind Cloudflare, which blocks Python-urllib's User-Agent (403, "error code: 1010"). Always send an explicit User-Agent.
- Jev noul answers carry no `confidence`; only choice/score do. Never write policy code that reads `confidence` from a noul.
- Jev reads dates as text. All date ordering/arithmetic happens in Python; Jev only sees labels like `earlier_memory` / `later_memory`.
- Before trusting any category-level benchmark number, read per-case traces. A 0% category in the first smoke run turned out to be an answer-prompt artifact (the agent abstained because it "cannot search for gyms") even though retrieval was perfect.
- Ruff autofix can rewrite readable code (SIM905 exploded a stopword string into a 1,100-char list). Check what `--fix` changed before committing.
