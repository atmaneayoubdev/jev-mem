import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, MODES, type CompareResponse, type DemoQuery, type Mode, type PublicConfig } from '../api';
import { JudgeMarker, QueryChips } from '../components/Controls';
import { EmptyState, ErrorNotice, Loading } from '../components/Notice';
import { fmtDate, fmtMs } from '../format';
import { useElapsed } from '../hooks';
import { isJudgedMode, modeLabel } from '../recall';
import type { Navigate, Params } from '../route';
import { CompareColumns } from './CompareColumns';
import './compare.css';

const DEFAULT_MODES: Mode[] = ['embedding', 'hybrid'];

interface CompareViewProps {
  user: string;
  params: Params;
  navigate: Navigate;
  config: PublicConfig | undefined;
  demoQueries: DemoQuery[];
  now: string | undefined;
}

function parseModes(raw: string | undefined, available: readonly Mode[]): Mode[] {
  const wanted = raw ? raw.split(',') : DEFAULT_MODES;
  const picked = available.filter((m) => wanted.includes(m));
  return picked.length > 0 ? picked : available.filter((m) => DEFAULT_MODES.includes(m));
}

export function CompareView({ user, params, navigate, config, demoQueries, now }: CompareViewProps) {
  const ids = useId();
  const available = config?.modes ?? [...MODES];
  const modes = parseModes(params.cm, available);
  const [draft, setDraft] = useState(params.q ?? '');
  const [result, setResult] = useState<{ data: CompareResponse; ms: number; query: string } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const elapsed = useElapsed(pending);
  const ctrlRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (query: string, runModes: Mode[]) => {
      const q = query.trim();
      if (!q || runModes.length === 0) return;
      ctrlRef.current?.abort();
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      setPending(true);
      setError(null);
      const started = performance.now();
      try {
        const data = await api.compare({ user_id: user, query: q, modes: runModes, now }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setResult({ data, ms: performance.now() - started, query: q });
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError(0, 'client_error', String(err)));
      } finally {
        if (!ctrl.signal.aborted) setPending(false);
      }
    },
    [user, now],
  );

  // Run whatever the URL describes: on load with ?q=, and again when modes, user or date change.
  const q = params.q;
  const modesKey = modes.join(',');
  useEffect(() => {
    if (!q) return;
    void run(q, modesKey.split(',') as Mode[]);
  }, [q, modesKey, run]);

  useEffect(() => () => ctrlRef.current?.abort(), []);

  function submit(query: string) {
    const text = query.trim();
    if (!text) return;
    setDraft(text);
    if (text === q) void run(text, modes);
    else navigate({ params: { q: text } }, { replace: true });
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submit(draft);
  }

  function toggleMode(m: Mode, on: boolean) {
    const next = available.filter((x) => (x === m ? on : modes.includes(x)));
    if (next.length === 0) return;
    navigate({ params: { cm: next.join(',') } }, { replace: true });
  }

  return (
    <div className="compare-view">
      <header className="compare-hero">
        <h1 className="thesis">
          <span>Vector search retrieves memories that look similar.</span>{' '}
          <span>JevMem asks which ones should matter now.</span>
        </h1>
        <p className="thesis-sub muted">
          Run one query through several retrieval modes at once. Similarity modes send their top results straight to the
          model; judged modes let Jev score relevance and utility, then a deterministic policy decides.
        </p>
      </header>

      <div className="compare-controls panel panel-pad">
        <form className="compare-form" onSubmit={onSubmit}>
          <div className="field compare-query">
            <label htmlFor={`${ids}-q`}>Query</label>
            <input
              id={`${ids}-q`}
              className="input"
              type="search"
              value={draft}
              maxLength={4000}
              placeholder="Ask something that depends on what the user said before"
              onChange={(e) => setDraft(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={pending || !draft.trim()}>
            {pending ? `Comparing (${elapsed}s)` : 'Compare'}
          </button>
        </form>

        <fieldset className="mode-checks">
          <legend className="field-label">Columns</legend>
          <div className="mode-checks-row">
            {available.map((m) => (
              <label key={m} className="check">
                <input
                  type="checkbox"
                  checked={modes.includes(m)}
                  onChange={(e) => toggleMode(m, e.target.checked)}
                  disabled={modes.length === 1 && modes.includes(m)}
                />
                {modeLabel(m)}
                {isJudgedMode(m) && <JudgeMarker />}
              </label>
            ))}
          </div>
        </fieldset>

        <QueryChips queries={demoQueries} onPick={(dq) => submit(dq.query)} disabled={pending} label="Demo queries" />
      </div>

      <div className="compare-results" aria-live="polite" aria-busy={pending}>
        {error && <ErrorNotice error={error} onRetry={() => submit(draft)} onDismiss={() => setError(null)} />}
        {pending && !result && <Loading>Retrieving and judging in {modes.length} modes</Loading>}
        {!pending && !result && !error && (
          <EmptyState title="Pick a demo query or type your own">
            Start with “Deploy my new service using my preferred cloud.” and follow the superseded AWS preference and the
            pasted vendor email across the columns.
          </EmptyState>
        )}
        {result && (
          <>
            <p className="compare-meta small muted">
              <span>
                “{result.query}” for {user}
              </span>
              <span>as of {fmtDate(Object.values(result.data)[0]?.now ?? now ?? new Date().toISOString())}</span>
              <span>round trip {fmtMs(result.ms)}</span>
              {pending && <span>updating ({elapsed}s)</span>}
            </p>
            {result.ms < 0.8 * Math.max(0, ...Object.values(result.data).map((o) => o?.judge_ms ?? 0)) && (
              <p className="compare-meta small muted">
                Judge times below are as first measured: cached model responses report their original latency, so
                they can exceed the round trip.
              </p>
            )}
            <CompareColumns results={result.data} order={available} policy={config?.policy} />
          </>
        )}
      </div>
    </div>
  );
}
