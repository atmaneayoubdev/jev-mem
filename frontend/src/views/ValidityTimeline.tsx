import { useMemo, useRef, type ReactNode } from 'react';
import type { MemoryLink, MemoryListItem } from '../api';
import { fmtDate, fmtMonth, fmtShortDate } from '../format';
import { useAnchorRects } from '../hooks';
import { slotGroups, validityEnd, VALIDITY_LABEL } from '../recall';

interface ValidityTimelineProps {
  memories: readonly MemoryListItem[];
  links: readonly MemoryLink[];
  ttlDays?: Record<string, number>;
  /** The time validity was computed at (the server's now). */
  now: Date;
  selectedId?: string;
  onSelect: (id: string) => void;
}

const DAY = 86_400_000;

function monthStart(t: number): Date {
  const d = new Date(t);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
}

function nextMonth(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
}

/**
 * Every memory on one time axis, grouped by slot (memories linked by supersession, override,
 * conflict or reinforcement sit together), so hand-offs like AWS to Azure read at a glance.
 */
export function ValidityTimeline({ memories, links, ttlDays, now, selectedId, onSelect }: ValidityTimelineProps) {
  const ref = useRef<HTMLDivElement>(null);
  const byId = useMemo(() => new Map(memories.map((m) => [m.id, m])), [memories]);
  const groups = useMemo(() => slotGroups(memories, links), [memories, links]);

  const spans = useMemo(() => {
    const out = new Map<string, { start: number; end: number; endKind: 'open' | 'superseded' | 'expires' }>();
    for (const m of memories) {
      const start = new Date(m.observed_at).getTime();
      const end = validityEnd(m, links, byId, ttlDays);
      if (end) out.set(m.id, { start, end: end.at.getTime(), endKind: end.kind });
      else out.set(m.id, { start, end: now.getTime(), endKind: 'open' });
    }
    return out;
  }, [memories, links, byId, ttlDays, now]);

  const [lo, hi] = useMemo(() => {
    let min = now.getTime();
    let max = now.getTime();
    for (const s of spans.values()) {
      min = Math.min(min, s.start);
      max = Math.max(max, s.end);
    }
    return [monthStart(min).getTime(), nextMonth(monthStart(max + 3 * DAY)).getTime()];
  }, [spans, now]);

  const ticks = useMemo(() => {
    const t: Date[] = [];
    for (let d = new Date(lo); d.getTime() <= hi; d = nextMonth(d)) t.push(d);
    return t;
  }, [lo, hi]);

  const frac = (t: number) => (hi === lo ? 0 : Math.max(0, Math.min(1, (t - lo) / (hi - lo))));
  const layout = useAnchorRects(ref, [memories, links, lo, hi]);

  // Hand-offs: a superseded memory ends where the memory that superseded it begins.
  const connectors = useMemo(() => {
    const out: { id: string; from: string; to: string; at: number; kind: string }[] = [];
    for (const l of links) {
      const src = byId.get(l.source_id);
      const tgt = byId.get(l.target_id);
      if (!src || !tgt) continue;
      const at = new Date(src.observed_at).getTime();
      if (l.link_type === 'supersedes') {
        const span = spans.get(tgt.id);
        if (span?.endKind === 'superseded' && span.end === at) out.push({ id: l.id, from: tgt.id, to: src.id, at, kind: 'supersedes' });
      } else if (l.link_type === 'conflicts_with' || l.link_type === 'temporarily_overrides') {
        out.push({ id: l.id, from: tgt.id, to: src.id, at, kind: l.link_type });
      }
    }
    return out;
  }, [links, byId, spans]);

  const rectOf = new Map(layout.rects.map((r) => [r.key, r]));
  const firstTrack = layout.rects[0];
  const lastTrack = layout.rects[layout.rects.length - 1];
  const overlay: ReactNode[] = [];
  if (firstTrack && lastTrack && layout.width > 0) {
    const w = firstTrack.right - firstTrack.left;
    const xAt = (t: number) => firstTrack.left + frac(t) * w;
    for (const tk of ticks) {
      overlay.push(
        <line key={`tick-${tk.getTime()}`} className="vt-gridline" x1={xAt(tk.getTime())} x2={xAt(tk.getTime())} y1={firstTrack.top - 4} y2={lastTrack.bottom + 4} />,
      );
    }
    overlay.push(
      <line key="today" className="vt-today" x1={xAt(now.getTime())} x2={xAt(now.getTime())} y1={firstTrack.top - 10} y2={lastTrack.bottom + 4} />,
    );
    for (const c of connectors) {
      const a = rectOf.get(c.from);
      const b = rectOf.get(c.to);
      if (!a || !b) continue;
      const x = xAt(c.at);
      overlay.push(<path key={c.id} className={`vt-link vt-link-${c.kind}`} d={`M${x},${a.cy} L${x},${b.cy}`} />);
    }
  }

  return (
    <figure className="vt" aria-label="Validity of every memory over time">
      <div className="vt-inner" ref={ref}>
        <div className="vt-axis" aria-hidden="true">
          <span className="vt-axis-label" />
          <span className="vt-axis-track">
            {ticks.map((tk, i) => (
              <span
                key={tk.getTime()}
                className={`vt-tick${Math.abs(frac(tk.getTime()) - frac(now.getTime())) < 0.045 ? ' is-near-today' : ''}`}
                style={{ left: `${frac(tk.getTime()) * 100}%` }}
              >
                {i === 0 || tk.getUTCMonth() === 0 ? `${fmtMonth(tk)} ${tk.getUTCFullYear()}` : fmtMonth(tk)}
              </span>
            ))}
            <span className="vt-today-label" style={{ left: `${frac(now.getTime()) * 100}%` }}>
              Today
            </span>
          </span>
          <span className="vt-axis-state" />
        </div>
        <ol className="vt-groups">
          {groups.map((g) => (
            <li key={g[0]?.id} className={`vt-group${g.length > 1 ? ' is-multi' : ''}`}>
              <ol className="vt-rows">
                {g.map((m) => {
                  const s = spans.get(m.id);
                  if (!s) return null;
                  const left = frac(s.start) * 100;
                  const width = Math.max(0.6, (frac(s.end) - frac(s.start)) * 100);
                  const endDate = fmtShortDate(new Date(s.end));
                  const stateText =
                    s.endKind === 'superseded'
                      ? `Superseded ${endDate}`
                      : m.validity === 'expired'
                        ? s.endKind === 'expires'
                          ? `Expired ${endDate}`
                          : 'Expired'
                        : s.endKind === 'expires'
                          ? `${VALIDITY_LABEL[m.validity]}, until ${endDate}`
                          : VALIDITY_LABEL[m.validity];
                  return (
                    <li key={m.id} className={`vt-row v-${m.validity}${selectedId === m.id ? ' is-selected' : ''}`}>
                      <button
                        type="button"
                        className="vt-label"
                        onClick={() => onSelect(m.id)}
                        aria-pressed={selectedId === m.id}
                        title={m.content}
                      >
                        <span className="vt-date">{fmtShortDate(m.observed_at)}</span>
                        <span className="vt-text memory-text">{m.content}</span>
                      </button>
                      <span
                        className="vt-track"
                        data-anchor={m.id}
                        role="img"
                        aria-label={`${fmtDate(m.observed_at)} to ${s.endKind === 'open' ? 'now' : fmtDate(new Date(s.end).toISOString())}: ${stateText}`}
                      >
                        <span className={`vt-bar vt-bar-${m.validity} vt-end-${s.endKind}`} style={{ left: `${left}%`, width: `${width}%` }} />
                        <span className="vt-start" style={{ left: `${left}%` }} />
                      </span>
                      <span className="vt-state">{stateText}</span>
                    </li>
                  );
                })}
              </ol>
            </li>
          ))}
        </ol>
        <svg className="vt-overlay" width={layout.width} height={layout.height} aria-hidden="true">
          {overlay}
        </svg>
      </div>
      <figcaption className="vt-legend small muted">
        <span>
          <span className="vt-key vt-key-current" aria-hidden="true" /> Current
        </span>
        <span>
          <span className="vt-key vt-key-superseded" aria-hidden="true" /> Superseded, ends where its successor starts
        </span>
        <span>
          <span className="vt-key vt-key-expired" aria-hidden="true" /> Expired temporary state (policy TTL)
        </span>
        <span>
          <span className="vt-key vt-key-conflict" aria-hidden="true" /> Conflict
        </span>
        <span>Validity as of today on the server; the as-of date does not apply here.</span>
      </figcaption>
    </figure>
  );
}
