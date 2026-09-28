import type { Decision } from '../api';
import { decisionMeta } from '../recall';

/**
 * Decision glyphs. Shape carries the meaning before colour does:
 * filled = injected into the context, outline = withheld; the inner mark names the reason.
 */
export function DecisionIcon({ decision, size = 14 }: { decision: string; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 14 14', 'aria-hidden': true, focusable: false } as const;
  switch (decision as Decision) {
    case 'use':
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5.5" fill="currentColor" />
        </svg>
      );
    case 'conflict':
      return (
        <svg {...common}>
          <path d="M7 1.4 L12.9 12 H1.1 Z" fill="currentColor" />
          <path d="M7 5.2 V8.4" stroke="var(--surface)" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="7" cy="10.2" r="0.85" fill="var(--surface)" />
        </svg>
      );
    case 'unjudged':
      return (
        <svg {...common}>
          <rect x="2" y="2" width="10" height="10" rx="2" fill="currentColor" />
        </svg>
      );
    case 'keep':
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case 'stale':
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M7 4.2 V7.2 L9.1 8.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case 'uncertain':
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
        </svg>
      );
    case 'drop':
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M3.6 10.4 L10.4 3.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
  }
}

export function DecisionBadge({ decision, compact = false }: { decision: string; compact?: boolean }) {
  const meta = decisionMeta(decision);
  return (
    <span
      className={`badge badge-${decision}${meta.injected ? ' badge-injected' : ''}${compact ? ' badge-compact' : ''}`}
      title={meta.description}
    >
      <DecisionIcon decision={decision} />
      <span>{meta.label}</span>
    </span>
  );
}

/** Injected / not injected marker for baseline rows (no judgment). */
export function InjectedMark({ injected }: { injected: boolean }) {
  return (
    <span className={`inj-mark${injected ? ' is-injected' : ''}`}>
      <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
        {injected ? (
          <circle cx="7" cy="7" r="5.5" fill="currentColor" />
        ) : (
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        )}
      </svg>
      {injected ? 'Injected' : 'Not injected'}
    </span>
  );
}
