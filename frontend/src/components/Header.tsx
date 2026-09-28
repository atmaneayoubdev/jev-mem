import type { ApiError, CircuitState, Health, PublicConfig } from '../api';
import { buildHash, VIEW_LABEL, VIEWS, type Route } from '../route';

type Tone = 'ok' | 'warn' | 'bad';

function StatusGlyph({ tone }: { tone: Tone }) {
  return (
    <svg className={`status-glyph status-${tone}`} width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
      {tone === 'ok' && <circle cx="5" cy="5" r="4" fill="currentColor" />}
      {tone === 'warn' && (
        <>
          <circle cx="5" cy="5" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M5 1.4 A3.6 3.6 0 0 1 5 8.6 Z" fill="currentColor" />
        </>
      )}
      {tone === 'bad' && (
        <path d="M2 2 L8 8 M8 2 L2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      )}
    </svg>
  );
}

function providerStatus(
  configured: boolean,
  circuit: CircuitState | undefined,
): { tone: Tone; text: string } {
  if (!configured) return { tone: 'bad', text: 'not configured' };
  if (circuit === undefined) return { tone: 'ok', text: 'configured' };
  if (circuit.state === 'closed') return { tone: 'ok', text: 'circuit closed' };
  const why = circuit.last_error ? `: ${circuit.last_error}` : '';
  if (circuit.state === 'half-open') return { tone: 'warn', text: `circuit half-open${why}` };
  return { tone: 'bad', text: `circuit open${why}` };
}

export function HealthStatus({
  health,
  config,
  error,
}: {
  health: Health | undefined;
  config: PublicConfig | undefined;
  error: ApiError | null;
}) {
  if (error) {
    return (
      <div className="health" role="status">
        <span className="health-item">
          <StatusGlyph tone="bad" />
          <span>API unreachable</span>
        </span>
      </div>
    );
  }
  if (!health) {
    return (
      <div className="health" role="status">
        <span className="health-item muted">Checking the server</span>
      </div>
    );
  }
  const jev = providerStatus(health.jev_configured, health.circuit.jev);
  const qwen = providerStatus(health.qwen_configured, health.circuit.qwen);
  const items: { name: string; tone: Tone; text: string; title: string }[] = [
    { name: 'Jev', ...jev, title: 'Decision model (judge)' },
    { name: 'Qwen', ...qwen, title: 'Answer and extraction model' },
    {
      name: 'Embeddings',
      tone: health.embeddings ? 'ok' : 'bad',
      text: health.embeddings ? 'on' : 'off',
      title: 'Dense retrieval',
    },
  ];
  if (config) {
    items.push({
      name: 'Debug output',
      tone: config.debug_payloads ? 'ok' : 'warn',
      text: config.debug_payloads ? 'exposed' : 'hidden',
      title: 'Whether recall traces (memory_debug) are returned',
    });
  }
  return (
    <div className="health" aria-label="Server status">
      {items.map((i) => (
        <span className="health-item" key={i.name} title={i.title}>
          <StatusGlyph tone={i.tone} />
          <span className="health-name">{i.name}</span>
          <span className="health-state">{i.text}</span>
        </span>
      ))}
      <span className="health-item health-version muted">v{health.version}</span>
    </div>
  );
}

export function Header({
  route,
  health,
  config,
  healthError,
}: {
  route: Route;
  health: Health | undefined;
  config: PublicConfig | undefined;
  healthError: ApiError | null;
}) {
  return (
    <header className="masthead">
      <div className="page masthead-inner">
        <a className="brand" href={buildHash({ view: 'chat', params: route.params })}>
          <svg width="22" height="16" viewBox="0 0 32 22" aria-hidden="true" focusable="false">
            <circle cx="9" cy="11" r="7" fill="currentColor" />
            <circle cx="23" cy="11" r="5.6" fill="none" stroke="currentColor" strokeWidth="2.2" />
          </svg>
          <span>JevMem</span>
        </a>
        <nav className="tabs" aria-label="Views">
          <ul>
            {VIEWS.map((v) => (
              <li key={v}>
                <a
                  href={buildHash({ view: v, params: route.params })}
                  aria-current={route.view === v ? 'page' : undefined}
                  className={`tab${route.view === v ? ' is-current' : ''}`}
                >
                  {VIEW_LABEL[v]}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <HealthStatus health={health} config={config} error={healthError} />
      </div>
    </header>
  );
}
