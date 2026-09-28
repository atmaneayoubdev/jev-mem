import { useMemo, useRef, useState } from 'react';
import type { Lineage, Memory, MemoryLink, Validity } from '../api';
import { fmtDate, fmtProb, fmtShortDate, truncate } from '../format';
import { useAnchorRects } from '../hooks';
import { byObserved, linkLabel, linkProbability, nodeStateLabel, topProbabilities, uniqueLinks } from '../recall';

type KnownMemory = Memory & { validity?: Validity };

interface LineageTimelineProps {
  lineage: Lineage;
  /** Links found in other memories' lineages, so edges between chain members are complete. */
  extraLinks?: readonly MemoryLink[];
  /** Memories known from the list endpoint (adds validity, resolves link endpoints). */
  memoriesById?: ReadonlyMap<string, KnownMemory>;
  onSelect?: (id: string) => void;
}

/** Line sample for an edge type; the same style is used for its arc. */
function EdgeGlyph({ type }: { type: string }) {
  return (
    <svg className={`edge-glyph arc-${type}`} width="22" height="10" viewBox="0 0 22 10" aria-hidden="true">
      <path d="M1 5 H17" className="arc-line" />
      <path d="M15 1.8 L20 5 L15 8.2" className="arc-head" />
    </svg>
  );
}

export function LineageTimeline({ lineage, extraLinks = [], memoriesById, onSelect }: LineageTimelineProps) {
  const focal = lineage.memory;
  const [activeLink, setActiveLink] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const { nodes, edges } = useMemo(() => {
    const byId = new Map<string, KnownMemory>();
    const add = (m: KnownMemory | undefined) => {
      if (m && !byId.has(m.id)) byId.set(m.id, memoriesById?.get(m.id) ?? m);
    };
    add(focal);
    lineage.chain.forEach(add);
    lineage.duplicates.forEach(add);
    lineage.conflicts.forEach(add);
    for (const l of lineage.links) {
      add(memoriesById?.get(l.source_id));
      add(memoriesById?.get(l.target_id));
    }
    const all = uniqueLinks([...lineage.links, ...extraLinks]).filter(
      (l) => byId.has(l.source_id) && byId.has(l.target_id),
    );
    return { nodes: [...byId.values()].sort(byObserved), edges: all };
  }, [focal, lineage, extraLinks, memoriesById]);

  const layout = useAnchorRects(ref, [nodes.length, edges.length, lineage.memory.id]);
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const outgoing = (id: string) =>
    edges
      .filter((e) => e.source_id === id)
      .sort((a, b) => (index.get(b.target_id) ?? 0) - (index.get(a.target_id) ?? 0));

  const validityOf = (n: KnownMemory): Validity | undefined =>
    n.id === focal.id ? lineage.validity : (memoriesById?.get(n.id)?.validity ?? n.validity);

  return (
    <div className="lineage" ref={ref}>
      <ol className="lin-nodes" aria-label="Lineage in date order">
        {nodes.map((n) => {
          const validity = validityOf(n);
          const state = nodeStateLabel(validity, n.status);
          const isFocal = n.id === focal.id;
          const out = outgoing(n.id);
          return (
            <li key={n.id} className={`lin-node${isFocal ? ' is-focal' : ''} state-${(validity ?? n.status).toLowerCase()}`}>
              <span className="lin-dot" data-anchor={n.id} aria-hidden="true" />
              <div className="lin-body">
                <p className="lin-head">
                  <time dateTime={n.observed_at}>{fmtDate(n.observed_at)}</time>
                  <span className={`lin-state state-chip-${(validity ?? n.status).toLowerCase()}`}>{state}</span>
                  {isFocal && <span className="lin-focal-tag">Selected</span>}
                  {n.instruction_like && <span className="lin-flag">Instruction-like</span>}
                </p>
                {isFocal || !onSelect ? (
                  <p className="memory-text lin-content">{n.content}</p>
                ) : (
                  <button type="button" className="lin-content-btn memory-text" onClick={() => onSelect(n.id)}>
                    {n.content}
                    <span className="sr-only"> (show this memory’s lineage)</span>
                  </button>
                )}
                {out.length > 0 && (
                  <ul className="lin-edges" aria-label="Relations to earlier memories">
                    {out.map((e) => {
                      const target = nodeById.get(e.target_id);
                      const p = linkProbability(e);
                      return (
                        <li
                          key={e.id}
                          className={`lin-edge${activeLink === e.id ? ' is-active' : ''}`}
                          onMouseEnter={() => setActiveLink(e.id)}
                          onMouseLeave={() => setActiveLink(null)}
                          title={`Judged by ${e.judge}${e.confidence !== null ? `, confidence ${fmtProb(e.confidence)}` : ''}${e.policy_version ? `, policy ${e.policy_version}` : ''}`}
                        >
                          <EdgeGlyph type={e.link_type} />
                          <span className="lin-edge-main">
                            <span className="lin-edge-type">{linkLabel(e.link_type)}</span>
                            <span className="lin-edge-p">
                              {e.link_type === 'uncertain_relation'
                                ? topProbabilities(e, 2)
                                    .map(([k, v]) => `${k} ${fmtProb(v)}`)
                                    .join(', ')
                                : p
                                  ? `p ${fmtProb(p.p)}`
                                  : ''}
                            </span>
                          </span>
                          <span className="lin-edge-target">
                            {target
                              ? `${fmtShortDate(target.observed_at)}: ${truncate(target.content, 64)}`
                              : e.target_id.slice(0, 8)}
                          </span>
                          {e.expires_at && <span className="lin-edge-exp">until {fmtDate(e.expires_at)}</span>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <Arcs edges={edges} layout={layout} index={index} activeLink={activeLink} />
    </div>
  );
}

function Arcs({
  edges,
  layout,
  index,
  activeLink,
}: {
  edges: MemoryLink[];
  layout: ReturnType<typeof useAnchorRects>;
  index: Map<string, number>;
  activeLink: string | null;
}) {
  if (layout.rects.length === 0 || layout.width === 0) return null;
  const dot = new Map(layout.rects.map((r) => [r.key, r]));
  return (
    <svg className="lin-arcs" width={layout.width} height={layout.height} aria-hidden="true">
      {edges.map((e) => {
        const s = dot.get(e.source_id);
        const t = dot.get(e.target_id);
        if (!s || !t) return null;
        const span = Math.abs((index.get(e.source_id) ?? 0) - (index.get(e.target_id) ?? 0));
        const x = s.left - 3;
        const tx = t.left - 3;
        const d = Math.min(10 + span * 9, Math.max(12, s.left - 6));
        const cls = `arc arc-${e.link_type}${activeLink === e.id ? ' is-active' : ''}${activeLink && activeLink !== e.id ? ' is-dim' : ''}`;
        // Arcs leave the later memory and arrive horizontally at the earlier one.
        return (
          <g key={e.id} className={cls}>
            <path className="arc-line" d={`M${x},${s.cy} C${x - d},${s.cy} ${tx - d},${t.cy} ${tx},${t.cy}`} />
            <path className="arc-head" d={`M${tx - 5.5},${t.cy - 3.5} L${tx},${t.cy} L${tx - 5.5},${t.cy + 3.5}`} />
          </g>
        );
      })}
    </svg>
  );
}
