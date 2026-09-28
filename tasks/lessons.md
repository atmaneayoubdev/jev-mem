# Lessons

Rules learned from corrections and surprises on this project. Review at session start.

- The Qwen endpoint sits behind Cloudflare, which blocks Python-urllib's User-Agent (403, "error code: 1010"). Always send an explicit User-Agent.
- Jev noul answers carry no `confidence`; only choice/score do. Never write policy code that reads `confidence` from a noul.
- Jev reads dates as text. All date ordering/arithmetic happens in Python; Jev only sees labels like `earlier_memory` / `later_memory`.
