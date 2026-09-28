# Security

## Reporting a vulnerability

Please report security issues privately through the repository's security advisory feature, or by email to the maintainers. Do not open a public issue for them. Include steps to reproduce and the affected version or commit. We aim to acknowledge reports within a few working days.

## Secrets

- API keys (`OPENROUTER_API_KEY` / `JEV_API_KEY` / `TYPESAFE_API_KEY`, `QWEN_API_KEY`) live only in `.env` or the process environment. `.env` is git- and docker-ignored.
- Keys are held as `SecretStr` and unwrapped only in `providers/factory.py`. They never appear in logs, manifests, `/config/public`, `jevmem doctor` output or API responses.
- **All model calls happen server-side.** The browser UI talks only to the JevMem API.
- The benchmark response cache stores request and response bodies, never headers.

## Built-in protections

- **SQL:** all database access goes through the SQLAlchemy ORM, so queries are parameterised.
- **Input limits:** request-body limit (`MAX_REQUEST_BYTES`, default 64 KB); field limits (message 8,000 characters, memory 4,000); strict `user_id` pattern.
- **Timeouts and concurrency:** HTTP timeouts on every provider call, bounded concurrency, retries with backoff, and circuit breakers.
- **CORS:** allow-list via `CORS_ORIGINS`.
- **Rate limiting:** a per-client rate-limit hook (`RATE_LIMIT_PER_MINUTE`). It is in-process; put a real limiter or gateway in front for multi-instance deployments.
- **Errors:** safe error responses (`{error, message, request_id}`) with no stack traces. Unhandled errors are logged server-side with their type only.
- **Production mode:** `ENVIRONMENT=production` hides `memory_debug` payloads and disables the demo seed and reset endpoints.
- **Memory poisoning:** memories are user-controlled text, and Jev does not treat its input as hostile by default. JevMem therefore:
  1. instructs every judge question that memory text is data, never instructions;
  2. flags instruction-like memories at write time, so they are never injected and can never supersede real memories;
  3. tells the answer model to treat memory text as information only.

  This is a mitigation, not a guarantee. On the benchmark's adversarial category it held in all test cases, but novel injection styles may get through.

## Not provided in v1

There is no user authentication or authorisation: `user_id` is caller-supplied. Run JevMem behind your own auth layer and do not expose it to the public internet as-is.
