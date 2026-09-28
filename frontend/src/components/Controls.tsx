import { useId, useState, type ReactNode } from 'react';
import type { DemoQuery } from '../api';
import { capitalize } from '../format';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** Small marker after the label (e.g. judged modes). */
  marker?: ReactNode;
}

/** Segmented control built on native radios: arrow keys, labels and focus come for free. */
export function SegmentedControl<T extends string>({
  legend,
  options,
  value,
  onChange,
  disabled,
  describedBy,
}: {
  legend: string;
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
  describedBy?: string;
}) {
  const name = useId();
  return (
    <fieldset className="segmented" disabled={disabled} aria-describedby={describedBy}>
      <legend className="field-label">{legend}</legend>
      <div className="segmented-track">
        {options.map((o) => (
          <label key={o.value} className={`segment${o.value === value ? ' is-on' : ''}`}>
            <input
              type="radio"
              name={name}
              value={o.value}
              checked={o.value === value}
              onChange={() => onChange(o.value)}
            />
            <span>{o.label}</span>
            {o.marker}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Demo query chips. The note under them says what the hovered or focused query demonstrates. */
export function QueryChips({
  queries,
  onPick,
  disabled,
  label = 'Demo queries',
}: {
  queries: DemoQuery[];
  onPick: (q: DemoQuery) => void;
  disabled?: boolean;
  label?: string;
}) {
  const [hint, setHint] = useState<DemoQuery | null>(null);
  const noteId = useId();
  if (queries.length === 0) return null;
  return (
    <div className="chips-block">
      <p className="field-label" id={`${noteId}-label`}>
        {label}
      </p>
      <ul className="chips" aria-labelledby={`${noteId}-label`}>
        {queries.map((q) => (
          <li key={q.query}>
            <button
              type="button"
              className="query-chip"
              disabled={disabled}
              onClick={() => onPick(q)}
              onMouseEnter={() => setHint(q)}
              onMouseLeave={() => setHint(null)}
              onFocus={() => setHint(q)}
              onBlur={() => setHint(null)}
              aria-describedby={noteId}
              title={q.demonstrates}
            >
              {q.query}
            </button>
          </li>
        ))}
      </ul>
      <p className="chips-note" id={noteId} aria-live="polite">
        {hint ? capitalize(hint.demonstrates) : 'Point at a query to see what it demonstrates.'}
      </p>
    </div>
  );
}

/** Marker for modes that run the judge. */
export function JudgeMarker() {
  return (
    <span className="judge-marker" title="Judged by Jev">
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" focusable="false">
        <path d="M5 0.8 L9.2 5 L5 9.2 L0.8 5 Z" fill="currentColor" />
      </svg>
      <span className="sr-only">(judged by Jev)</span>
    </span>
  );
}
