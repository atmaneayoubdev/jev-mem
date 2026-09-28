import { Fragment, useMemo, useRef, useState, type ReactNode } from 'react';
import type { CompareResponse, Mode, Policy, RecallOutcome } from '../api';
import { CandidateRow } from '../components/CandidateRow';
import { DecisionBadge } from '../components/DecisionBadge';
import { JudgeMarker } from '../components/Controls';
import { FallbackDetail } from '../components/Notice';
import { fmtCost, fmtMs, plural } from '../format';
import { useAnchorRects, type AnchorRect } from '../hooks';
import {
  compareDisagreements,
  fallbackSummary,
  isJudgedMode,
  MODE_DESCRIPTION,
  modeLabel,
  orderedModes,
  recallRows,
  rowReason,
  splitInjected,
  type CompareDisagreement,
  type RecallRow,
} from '../recall';

interface CompareColumnsProps {
  results: CompareResponse;
  /** Column order (normally `config.modes`). */
  order: readonly Mode[];
  policy?: Policy;
}

const SCORE_HINT: Record<string, string> = {
  recency: 'Recency score',
  bm25: 'BM25 score',
  embedding: 'Cosine similarity',
  jev: 'BM25 score (first stage)',
  hybrid: 'Reciprocal-rank fusion score',
};

export function CompareColumns({ results, order, policy }: CompareColumnsProps) {
  const modes = orderedModes(results, order);
  const diffs = useMemo(() => compareDisagreements(results, modes), [results, modes]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const layout = useAnchorRects(gridRef, [results, modes.join(',')]);

  const selected = useMemo(() => {
    const m = new Map<Mode, Set<string>>();
    for (const mode of modes) m.set(mode, new Set(results[mode]?.selected_ids ?? []));
    return m;
  }, [results, modes]);

  const baselines = modes.filter((m) => !isJudgedMode(m));
  const judged = modes.filter((m) => isJudgedMode(m));

  /** Flags that tie a row to the other columns. */
  function flagsFor(mode: Mode, row: RecallRow): { node: ReactNode; contested: boolean } {
    const items: ReactNode[] = [];
    let contested = false;
    if (!isJudgedMode(mode) && row.injected) {
      for (const j of judged) {
        const jr = results[j];
        if (!jr || selected.get(j)?.has(row.id)) continue;
        const judgment = jr.judgments.find((x) => x.id === row.id);
        contested = true;
        items.push(
          <span key={j} className="xflag xflag-rejected">
            Withheld by {modeLabel(j)}
            {judgment && <DecisionBadge decision={judgment.decision} compact />}
          </span>,
        );
      }
    }
    if (isJudgedMode(mode)) {
      for (const b of baselines) {
        const inBase = selected.get(b)?.has(row.id) ?? false;
        if (inBase && !row.injected) {
          contested = true;
          items.push(
            <span key={b} className="xflag xflag-rejected">
              Injected by {modeLabel(b)}
            </span>,
          );
        } else if (!inBase && row.injected) {
          items.push(
            <span key={b} className="xflag xflag-added">
              Not injected by {modeLabel(b)}
            </span>,
          );
        }
      }
    }
    return { node: items.length > 0 ? <p className="xflags">{items}</p> : null, contested };
  }

  function renderRows(mode: Mode, rows: RecallRow[], outcome: RecallOutcome) {
    return (
      <ol className="cand-list cmp-list">
        {rows.map((r) => {
          const f = flagsFor(mode, r);
          return (
            <CandidateRow
              key={r.id}
              row={r}
              judged={isJudgedMode(outcome.mode)}
              policy={policy}
              compact
              scoreHint={SCORE_HINT[mode]}
              flag={f.node}
              highlighted={activeId === r.id}
              contested={f.contested}
              rowProps={{
                'data-anchor': r.id,
                'data-group': mode,
                onMouseEnter: () => setActiveId(r.id),
                onMouseLeave: () => setActiveId(null),
              }}
            />
          );
        })}
      </ol>
    );
  }

  return (
    <div className="cmp">
      <Summary diffs={diffs} results={results} baselines={baselines} judged={judged} />

      <div className="cmp-scroll">
        <div
          className={`cmp-grid${activeId ? ' has-active' : ''}`}
          ref={gridRef}
          style={{ ['--cols' as string]: String(modes.length) }}
        >
          {modes.map((mode) => {
            const outcome = results[mode];
            if (!outcome) return null;
            const rows = recallRows(outcome);
            const { injected, withheld } = splitInjected(rows);
            const isJ = isJudgedMode(mode);
            return (
              <section key={mode} className={`cmp-col${isJ ? ' is-judged' : ''}`} aria-labelledby={`cmp-h-${mode}`}>
                <header className="cmp-col-head">
                  <h3 id={`cmp-h-${mode}`}>
                    {modeLabel(mode)}
                    {isJ && <JudgeMarker />}
                  </h3>
                  <p className="small muted">{MODE_DESCRIPTION[mode]}</p>
                  <ColumnStats outcome={outcome} injected={injected.length} />
                </header>
                {isJ ? (
                  <>
                    <h4 className="cmp-group">
                      Injected <span className="count">{injected.length}</span>
                    </h4>
                    {injected.length > 0 ? (
                      renderRows(mode, injected, outcome)
                    ) : (
                      <p className="small muted cmp-none">Nothing injected.</p>
                    )}
                    <h4 className="cmp-group">
                      Withheld <span className="count">{withheld.length}</span>
                    </h4>
                    {withheld.length > 0 ? (
                      renderRows(mode, withheld, outcome)
                    ) : (
                      <p className="small muted cmp-none">Nothing withheld.</p>
                    )}
                  </>
                ) : (
                  <>
                    <h4 className="cmp-group">
                      Ranked by score <span className="count">{rows.length}</span>
                    </h4>
                    {renderRows(mode, rows, outcome)}
                  </>
                )}
              </section>
            );
          })}
          <Threads modes={modes} rects={layout.rects} width={layout.width} height={layout.height} selected={selected} activeId={activeId} />
        </div>
      </div>
    </div>
  );
}

function ColumnStats({ outcome: o, injected }: { outcome: RecallOutcome; injected: number }) {
  const cost = fmtCost(o.judge_cost);
  return (
    <dl className="cmp-stats">
      <div>
        <dt>Injected</dt>
        <dd>
          {injected} of {o.candidates.length}
        </dd>
      </div>
      <div>
        <dt>Context</dt>
        <dd>{plural(o.context_tokens, 'token')}</dd>
      </div>
      <div>
        <dt>Retrieval</dt>
        <dd>{fmtMs(o.retrieval_ms)}</dd>
      </div>
      <div>
        <dt>Judge</dt>
        <dd>
          {o.judge_used ? (
            <>
              {plural(o.judge_calls, 'call')}, {fmtMs(o.judge_ms)}
              {cost && <span className="muted">, {cost}</span>}
            </>
          ) : isJudgedMode(o.mode) ? (
            <div className="judge-fallback">
              <FallbackDetail summary={`Not used: ${fallbackSummary(o.fallback_reason)}`} raw={o.fallback_reason} />
            </div>
          ) : (
            <span className="muted">none</span>
          )}
        </dd>
      </div>
    </dl>
  );
}

function Summary({
  diffs,
  results,
  baselines,
  judged,
}: {
  diffs: CompareDisagreement[];
  results: CompareResponse;
  baselines: Mode[];
  judged: Mode[];
}) {
  if (baselines.length === 0 || judged.length === 0) {
    return (
      <p className="cmp-summary-empty small muted">
        Add a similarity mode (recency, BM25 or embedding) and a judged mode (Jev or hybrid) to see where they disagree.
      </p>
    );
  }
  return (
    <section className="cmp-summary panel panel-pad" aria-label="Where the modes disagree">
      {diffs.map((d) => {
        const base = results[d.baseline];
        const jr = results[d.judged];
        if (!base || !jr) return null;
        return (
          <div className="cmp-diff" key={`${d.baseline}-${d.judged}`}>
            <p className="cmp-diff-lede">
              {modeLabel(d.baseline)} injected {plural(base.selected_ids.length, 'memory', 'memories')}.{' '}
              {modeLabel(d.judged)} injected {jr.selected_ids.length}
              {d.withheld.length > 0 ? ` and withheld ${d.withheld.length} of ${modeLabel(d.baseline)}’s.` : '.'}
            </p>
            {d.withheld.length > 0 && (
              <>
                <h3 className="cmp-diff-h">
                  Injected by {modeLabel(d.baseline)}, withheld by {modeLabel(d.judged)}
                </h3>
                <ul className="diff-list">
                  {d.withheld.map(({ row, baselineRank, judgment }) => (
                    <li key={row.id} className="diff-item">
                      <span className="diff-badge">
                        {judgment ? <DecisionBadge decision={judgment.decision} /> : <span className="muted small">not judged</span>}
                      </span>
                      <span className="diff-body">
                        <span className="memory-text diff-content">{row.candidate?.content ?? row.id}</span>
                        <span className="diff-why small">
                          {judgment
                            ? rowReason(judgment.reason, judgment.decision).text
                            : `not among ${modeLabel(d.judged)}’s candidates`}
                          <span className="muted">
                            {' '}
                            ({modeLabel(d.baseline)} rank {baselineRank + 1})
                          </span>
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {d.added.length > 0 && (
              <>
                <h3 className="cmp-diff-h">
                  Injected by {modeLabel(d.judged)}, not by {modeLabel(d.baseline)}
                </h3>
                <ul className="diff-list">
                  {d.added.map(({ row, judgment }) => (
                    <li key={row.id} className="diff-item">
                      <span className="diff-badge">{judgment && <DecisionBadge decision={judgment.decision} />}</span>
                      <span className="diff-body">
                        <span className="memory-text diff-content">{row.candidate?.content ?? row.id}</span>
                        {judgment && (
                          <span className="diff-why small">{rowReason(judgment.reason, judgment.decision).text}</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {d.withheld.length === 0 && d.added.length === 0 && (
              <p className="small muted">Both injected the same memories for this query.</p>
            )}
          </div>
        );
      })}
    </section>
  );
}

/** Lines linking the same memory across adjacent columns (hidden when columns stack). */
function Threads({
  modes,
  rects,
  width,
  height,
  selected,
  activeId,
}: {
  modes: Mode[];
  rects: AnchorRect[];
  width: number;
  height: number;
  selected: Map<Mode, Set<string>>;
  activeId: string | null;
}) {
  if (rects.length === 0 || width === 0) return null;
  const byGroup = new Map<string, Map<string, AnchorRect>>();
  for (const r of rects) {
    const g = byGroup.get(r.group) ?? new Map<string, AnchorRect>();
    g.set(r.key, r);
    byGroup.set(r.group, g);
  }
  const paths: ReactNode[] = [];
  for (let i = 0; i < modes.length - 1; i++) {
    const a = modes[i] as Mode;
    const b = modes[i + 1] as Mode;
    const ga = byGroup.get(a);
    const gb = byGroup.get(b);
    if (!ga || !gb) continue;
    // Columns stacked (narrow screens): no threads.
    const anyA = ga.values().next().value;
    const anyB = gb.values().next().value;
    if (!anyA || !anyB || anyB.left <= anyA.right) continue;
    for (const [id, ra] of ga) {
      const rb = gb.get(id);
      if (!rb) continue;
      const inA = selected.get(a)?.has(id) ?? false;
      const inB = selected.get(b)?.has(id) ?? false;
      const active = activeId === id;
      if (!inA && !inB && !active) continue;
      const kind = inA && inB ? 'kept' : 'contested';
      const y1 = ra.top + Math.min(22, (ra.bottom - ra.top) / 2);
      const y2 = rb.top + Math.min(22, (rb.bottom - rb.top) / 2);
      const x1 = ra.right + 2;
      const x2 = rb.left - 2;
      const mx = (x1 + x2) / 2;
      paths.push(
        <Fragment key={`${a}-${b}-${id}`}>
          <path
            d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
            className={`thread thread-${kind}${active ? ' is-active' : ''}`}
          />
          <circle cx={x1} cy={y1} r={2.4} className={`thread-end thread-${kind}${active ? ' is-active' : ''}`} />
          <circle cx={x2} cy={y2} r={2.4} className={`thread-end thread-${kind}${active ? ' is-active' : ''}`} />
        </Fragment>,
      );
    }
  }
  return (
    <svg className="cmp-threads" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {paths}
    </svg>
  );
}
