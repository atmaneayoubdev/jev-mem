# JevMem

### Decision-native long-term memory for AI agents.

> Vector search retrieves memories that look similar.
> JevMem asks which memories should actually influence the agent.

**Status: under active development (milestone 1: research core).** No benchmark results are published yet. Results will only appear here with their raw per-case data, manifest, and reproduction instructions.

JevMem evaluates whether decision-based retrieval, using [TypeSafe Jev](https://docs.typesafe.ai) as a calibrated judge and a deterministic policy that makes the final call, improves agent memory over similarity-only retrieval.

The full README, architecture docs, and benchmark methodology will land with the first results.

## Quick start (development)

```bash
uv sync
cp .env.example .env   # fill in keys; never commit .env
uv run pytest          # offline; no API keys needed
uv run jevmem doctor   # checks Jev + Qwen connectivity
```
