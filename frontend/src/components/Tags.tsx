import type { ReactNode } from 'react';
import { sourceLabel } from '../recall';

export function SourceTags({ sources }: { sources: string[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className="tags" aria-label="Retrieved by">
      {sources.map((s) => (
        <li key={s} className={`tag tag-source${s.startsWith('link:') ? ' tag-link' : ''}`}>
          {sourceLabel(s)}
        </li>
      ))}
    </ul>
  );
}

export function Annotations({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="tags" aria-label="Annotations">
      {items.map((a) => (
        <li key={a} className={`tag tag-note${a.startsWith('conflicting') ? ' tag-conflict' : ''}`}>
          {a}
        </li>
      ))}
    </ul>
  );
}

export function Chip({ children, tone }: { children: ReactNode; tone?: 'stale' | 'conflict' | 'use' | 'warn' }) {
  return <span className={`chip${tone ? ` chip-${tone}` : ''}`}>{children}</span>;
}

/** Validity/status chip: text always present, tone only reinforces it. */
export function ValidityChip({ validity, label }: { validity: string; label?: string }) {
  const lapsed = validity === 'superseded' || validity === 'expired' || validity === 'overridden';
  const text = label ?? validity.charAt(0).toUpperCase() + validity.slice(1);
  return (
    <span className={`chip chip-validity${lapsed ? ' chip-stale' : ''}${validity === 'archived' ? ' chip-archived' : ''}`}>
      {text}
    </span>
  );
}
