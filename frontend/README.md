# JevMem demo frontend

A single-page React app for the JevMem API. It shows which stored memories retrieval found, how Jev judged
each one, and what actually reached the model.

- **Chat and inspector**: chat as a user in any retrieval mode (recency, BM25, embedding, Jev, hybrid). For the
  selected answer, the inspector shows the candidates with their sources, Jev's relevance and utility, the
  policy decision and its reason, validity and annotations, query intent, judge usage, latency, context tokens,
  the exact context text sent to the model, and memories extracted from the turn.
- **Compare**: one query through several modes side by side. It highlights memories a similarity mode injected
  and JevMem withheld, for example the superseded AWS preference and the pasted vendor email.
- **Memories**: every memory on a validity timeline, a table with status, validity, durability and the
  instruction-like flag, archiving, and a lineage view of each memory's supersession chain and judged links.
- **Benchmark**: answer accuracy per system and run from `/api/v1/benchmark/runs` (the `test-main` run is
  highlighted), plus this server's counters and latencies from `/api/v1/metrics/summary`.

View state lives in the URL hash (`#/compare?u=alex&q=...`), so any view can be reloaded or shared.

## Requirements

- Node.js 22.12 or newer and npm
- The JevMem API server on `http://127.0.0.1:8765` (see the repository README)

## Develop

```sh
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (normally <http://127.0.0.1:5173>). The dev server proxies `/api` to
`http://127.0.0.1:8765`; change `BACKEND` in `vite.config.ts` if your API runs elsewhere. The app calls the
relative base `/api/v1`, so it needs no configuration beyond that proxy.

To load the demo user, choose **Seed demo** in the header bar. It writes the dated "alex" memories through the
write-time lifecycle, so Jev must be reachable. **Reset demo** deletes that user's memories and conversations.
Both are disabled by the server in production.

The **As of** date replays recall as if today were that date (the API's `now` override). It applies to chat and
compare. The memory table and lineage show validity as of the server's real current time, because those
endpoints do not accept `now`.

## Build

```sh
npm run build
```

This type-checks (`tsc --noEmit`, strict) and writes the production bundle to `frontend/dist/`. The FastAPI
app serves `frontend/dist/` at `/` when the directory exists at startup, so restart the API server after the
first build.

## Test

```sh
npm test
```

Vitest and Testing Library render the inspector, the compare view, the lineage timeline and the benchmark
table from the real API responses in `fixtures/`. They also check that those fixtures fit the TypeScript
types in `src/api.ts`, and that errors and judge fallbacks render cleanly. Use `npm run test:watch` while
developing.

## Layout

```
fixtures/            captured API responses (the contract)
src/api.ts           typed API client and error handling
src/recall.ts        pure derivations: rows, decisions, compare diffs, lineage and validity spans
src/route.ts         URL-hash state
src/components/      badges, score bars, meters, controls, notices
src/views/           chat and inspector, compare, memories (timeline, lineage), benchmark
src/styles/          design tokens (light and dark), base and component styles
src/test/            vitest suites
```

## Notes

- There are no UI kit, CSS framework or chart library dependencies. Charts, bars and connectors are
  hand-written SVG and CSS. The fonts (Atkinson Hyperlegible Next, Source Serif 4) are bundled from
  Fontsource, so the app makes no third-party requests.
- Light and dark themes follow `prefers-color-scheme`.
- Decisions are shown by glyph shape and label as well as colour: filled for injected, outline for withheld.
- If the server hides debug payloads (`memory_debug` is null, the default in production), the inspector says
  so and shows only latency and extracted memories.
- Latencies in traces come from the server. Cached model responses report the latency measured when they were
  first computed, so the inspector and compare view also show the round trip measured in the browser.
