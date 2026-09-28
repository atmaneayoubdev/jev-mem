import type { IntentView, LatencyMs } from '../api';
import { capitalize, fmtMs, fmtPct } from '../format';

const LATENCY_PARTS: { key: keyof LatencyMs; label: string }[] = [
  { key: 'retrieval', label: 'Retrieval' },
  { key: 'judge', label: 'Judge' },
  { key: 'generation', label: 'Generation' },
];

/** One stacked bar: retrieval, judge, generation. Values are also listed in text. */
export function LatencyBar({ latency }: { latency: Partial<LatencyMs> }) {
  const parts = LATENCY_PARTS.filter((p) => typeof latency[p.key] === 'number');
  const total = parts.reduce((s, p) => s + (latency[p.key] ?? 0), 0);
  return (
    <figure className="latency">
      <div className="latency-bar" aria-hidden="true">
        {parts.map((p, i) => {
          const v = latency[p.key] ?? 0;
          return (
            <span
              key={p.key}
              className={`latency-seg latency-seg-${i}`}
              style={{ flexGrow: total > 0 ? v / total : 0, minWidth: v > 0 ? 3 : 0 }}
            />
          );
        })}
      </div>
      <figcaption>
        <dl className="latency-legend">
          {parts.map((p, i) => (
            <div key={p.key}>
              <dt>
                <span className={`swatch latency-seg-${i}`} aria-hidden="true" />
                {p.label}
              </dt>
              <dd>{fmtMs(latency[p.key])}</dd>
            </div>
          ))}
          <div className="latency-total">
            <dt>Total</dt>
            <dd>{fmtMs(total)}</dd>
          </div>
        </dl>
      </figcaption>
    </figure>
  );
}

const INTENTS = ['current', 'historical', 'both'] as const;

/** Query intent with the judge's probabilities, when present. */
export function IntentMeter({ intent }: { intent: IntentView }) {
  const probs = intent.probabilities;
  return (
    <div className="intent">
      <p className="intent-head">
        <strong>{capitalize(intent.intent)}</strong>
        {probs && typeof probs[intent.intent] === 'number' && (
          <span className="muted"> {fmtPct(probs[intent.intent] ?? 0, 0)}</span>
        )}
        {intent.low_confidence && (
          <span className="muted">
            {' '}
            (low confidence{intent.judged ? `; judged ${intent.judged}` : ''}, so treated as both)
          </span>
        )}
      </p>
      {probs && (
        <>
          <div className="intent-bar" aria-hidden="true">
            {INTENTS.map((k) => (
              <span
                key={k}
                className={`intent-seg${k === intent.intent ? ' is-chosen' : ''}`}
                style={{ flexGrow: probs[k] ?? 0 }}
              />
            ))}
          </div>
          <ul className="intent-legend">
            {INTENTS.map((k) => (
              <li key={k} className={k === intent.intent ? 'is-chosen' : undefined}>
                {capitalize(k)} {fmtPct(probs[k] ?? 0, 0)}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
