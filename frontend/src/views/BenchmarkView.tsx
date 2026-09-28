import { useId, useMemo } from 'react';
import { api, type BenchmarkRun, type MetricsSummary } from '../api';
import { EmptyState, ErrorNotice, Loading } from '../components/Notice';
import { fmtDate, fmtInt, fmtMs, fmtPct, humanize } from '../format';
import { useAsync } from '../hooks';
import type { Navigate, Params } from '../route';
import './benchmark.css';

export const FEATURED_RUN = 'test-main';

interface BenchmarkViewProps {
  params: Params;
  navigate: Navigate;
}

export function BenchmarkView({ params, navigate }: BenchmarkViewProps) {
  const runs = useAsync((signal) => api.benchmarkRuns(signal), 'runs');
  const metrics = useAsync((signal) => api.metrics(signal), 'metrics');

  return (
    <div className="bench-view">
      <div className="section-head">
        <h1 className="view-title">Benchmark</h1>
        <p className="small muted">
          Answer accuracy per system, read from <code>benchmarks/results/&lt;run&gt;/metrics.json</code> by the API.
        </p>
      </div>
      {runs.error && <ErrorNotice error={runs.error} onRetry={runs.reload} />}
      {runs.loading && !runs.data && <Loading>Loading benchmark runs</Loading>}
      {runs.data && runs.data.length === 0 && (
        <EmptyState title="No benchmark runs found">
          Results appear here once <code>benchmarks/results/&lt;run&gt;/metrics.json</code> exists on the server.
        </EmptyState>
      )}
      {runs.data && runs.data.length > 0 && (
        <BenchmarkResults
          runs={runs.data}
          focus={params.run}
          onFocus={(run) => navigate({ params: { run } }, { replace: true })}
        />
      )}

      <section className="panel panel-pad metrics-panel" aria-labelledby="metrics-h">
        <div className="section-head">
          <h2 id="metrics-h">This server process</h2>
          <span className="small muted">Counters and latencies since the API server started</span>
        </div>
        {metrics.error && <ErrorNotice error={metrics.error} onRetry={metrics.reload} />}
        {metrics.loading && !metrics.data && <Loading>Loading metrics</Loading>}
        {metrics.data && <Metrics data={metrics.data} onRefresh={metrics.reload} />}
      </section>
    </div>
  );
}

export function BenchmarkResults({
  runs,
  focus,
  onFocus,
}: {
  runs: BenchmarkRun[];
  focus?: string;
  onFocus?: (run: string) => void;
}) {
  const ids = useId();
  const finished = runs.filter((r) => r.answer_accuracy && Object.keys(r.answer_accuracy).length > 0);
  // The featured run is pinned as the first data column; the rest keep the API's order.
  const columns = [
    ...finished.filter((r) => r.run_id === FEATURED_RUN),
    ...finished.filter((r) => r.run_id !== FEATURED_RUN),
  ];
  const live = runs.filter((r) => !r.answer_accuracy);
  const focusId =
    (focus && finished.some((r) => r.run_id === focus) ? focus : undefined) ??
    (finished.some((r) => r.run_id === FEATURED_RUN) ? FEATURED_RUN : finished[finished.length - 1]?.run_id);
  const focusRun = finished.find((r) => r.run_id === focusId);

  const systems = useMemo(() => {
    const s = new Set<string>();
    for (const r of finished) for (const k of Object.keys(r.answer_accuracy ?? {})) s.add(k);
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [finished]);

  const ranked = focusRun
    ? Object.entries(focusRun.answer_accuracy ?? {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    : [];

  return (
    <>
      {focusRun && (
        <section className="panel panel-pad bench-focus" aria-labelledby={`${ids}-focus`}>
          <div className="section-head">
            <h2 id={`${ids}-focus`}>
              <span>{focusRun.run_id}</span>
              {focusRun.run_id === FEATURED_RUN && <span className="featured-tag">Highlighted run</span>}
            </h2>
            <div className="field bench-pick">
              <label htmlFor={`${ids}-run`}>Run</label>
              <select
                id={`${ids}-run`}
                className="select"
                value={focusRun.run_id}
                onChange={(e) => onFocus?.(e.target.value)}
              >
                {finished.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="small muted bench-note">
            Answer accuracy by system, highest first. Bars start at zero. Systems whose name contains “jev” use Jev as
            the judge and are drawn in the darker tone.
          </p>
          <ol className="bench-bars">
            {ranked.map(([system, acc]) => (
              <li key={system} className={`bench-bar-row${/jev/.test(system) ? ' is-jev' : ''}`}>
                <span className="bench-sys">{system}</span>
                <span className="bench-track" aria-hidden="true">
                  <span className="bench-fill" style={{ width: `${Math.max(0, Math.min(1, acc)) * 100}%` }} />
                </span>
                <span className="bench-val" title={String(acc)}>
                  {fmtPct(acc)}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="panel bench-matrix-panel" aria-labelledby={`${ids}-matrix`}>
        <div className="section-head panel-pad-x">
          <h2 id={`${ids}-matrix`}>
            All runs <span className="count">{finished.length}</span>
          </h2>
          <span className="small muted">Answer accuracy; a dash means the run did not include that system</span>
        </div>
        <div className="bench-scroll" tabIndex={0} role="region" aria-label="Answer accuracy by system and run">
          <table className="bench-table">
            <thead>
              <tr>
                <th scope="col" className="bench-corner">
                  System
                </th>
                {columns.map((r) => (
                  <th
                    key={r.run_id}
                    scope="col"
                    className={`bench-run${r.run_id === FEATURED_RUN ? ' is-featured' : ''}${r.run_id === focusId ? ' is-focus' : ''}`}
                  >
                    {onFocus ? (
                      <button type="button" className="bench-run-btn" onClick={() => onFocus(r.run_id)}>
                        {r.run_id}
                      </button>
                    ) : (
                      r.run_id
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {systems.map((s) => (
                <tr key={s}>
                  <th scope="row" className="bench-sys-cell">
                    {s}
                  </th>
                  {columns.map((r) => {
                    const v = r.answer_accuracy?.[s];
                    return (
                      <td
                        key={r.run_id}
                        className={`${r.run_id === FEATURED_RUN ? 'is-featured' : ''}${r.run_id === focusId ? ' is-focus' : ''}`}
                        title={v === undefined ? undefined : String(v)}
                      >
                        {v === undefined ? <span className="muted">–</span> : fmtPct(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {live.length > 0 && (
        <section className="panel panel-pad" aria-label="Runs in progress">
          <h2>Started from the API</h2>
          <ul className="bench-live small">
            {live.map((r) => (
              <li key={r.run_id}>
                <code className="mono">{r.run_id}</code> {r.state ?? 'unknown'}
                {r.started && <span className="muted"> since {fmtDate(r.started)}</span>}
                {r.error && <span className="muted"> ({r.error})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function Metrics({ data, onRefresh }: { data: MetricsSummary; onRefresh: () => void }) {
  const counters = Object.entries(data.service.counters);
  const latencies = Object.entries(data.service.latency_ms);
  const clients = Object.entries(data.clients);
  return (
    <div className="metrics">
      <div className="metrics-grid">
        <div>
          <h3>Counters</h3>
          {counters.length === 0 ? (
            <p className="small muted">No activity yet.</p>
          ) : (
            <dl className="kv">
              {counters.map(([k, v]) => (
                <div key={k}>
                  <dt>{humanize(k)}</dt>
                  <dd>{fmtInt(v)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <div>
          <h3>Latency</h3>
          {latencies.length === 0 ? (
            <p className="small muted">No timings yet.</p>
          ) : (
            <div className="mini-scroll">
              <table className="mini-table">
                <thead>
                  <tr>
                    <th scope="col">Stage</th>
                    <th scope="col">Count</th>
                    <th scope="col">Mean</th>
                    <th scope="col">p50</th>
                    <th scope="col">p95</th>
                  </tr>
                </thead>
                <tbody>
                  {latencies.map(([k, v]) => (
                    <tr key={k}>
                      <th scope="row">{humanize(k.replace(/_ms$/, ''))}</th>
                      <td>{fmtInt(v.count)}</td>
                      <td>{fmtMs(v.mean)}</td>
                      <td>{fmtMs(v.p50)}</td>
                      <td>{fmtMs(v.p95)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div>
          <h3>Model clients</h3>
          <div className="mini-scroll">
            <table className="mini-table">
              <thead>
                <tr>
                  <th scope="col">Client</th>
                  <th scope="col">Requests</th>
                  <th scope="col">Cache hits</th>
                  <th scope="col">Retries</th>
                  <th scope="col">Errors</th>
                </tr>
              </thead>
              <tbody>
                {clients.map(([name, c]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td>{fmtInt(c.requests)}</td>
                    <td>{fmtInt(c.cache_hits)}</td>
                    <td>{fmtInt(c.retries)}</td>
                    <td>{fmtInt(c.errors)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <button type="button" className="btn btn-sm" onClick={onRefresh}>
        Refresh metrics
      </button>
    </div>
  );
}
