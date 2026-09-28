import type { HTMLAttributes, ReactNode } from 'react';
import type { Policy } from '../api';
import { fmtDate, fmtScore } from '../format';
import { rowReason, type RecallRow } from '../recall';
import { DecisionBadge, InjectedMark } from './DecisionBadge';
import { ScoreBar } from './ScoreBar';
import { Annotations, SourceTags, ValidityChip } from './Tags';

export interface CandidateRowProps {
  row: RecallRow;
  /** Whether this list came from a judged mode (jev, hybrid). */
  judged: boolean;
  policy?: Policy;
  /** Retriever score label for the title attribute. */
  scoreHint?: string;
  /** Extra line (e.g. cross-mode flags in compare). */
  flag?: ReactNode;
  compact?: boolean;
  highlighted?: boolean;
  /** Injected by one column and withheld by another (compare view). */
  contested?: boolean;
  rowProps?: Omit<HTMLAttributes<HTMLLIElement>, 'className'> & Record<`data-${string}`, string | undefined>;
}

export function CandidateRow({
  row,
  judged,
  policy,
  scoreHint,
  flag,
  compact,
  highlighted,
  contested,
  rowProps,
}: CandidateRowProps) {
  const c = row.candidate;
  const j = row.judgment;
  const read = policy?.read;
  const cls = [
    'cand',
    row.injected ? 'is-injected' : 'is-withheld',
    compact ? 'is-compact' : '',
    highlighted ? 'is-highlighted' : '',
    contested ? 'is-contested' : '',
    j ? `decision-${j.decision}` : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <li {...rowProps} className={cls}>
      <span className="cand-rank" title="Retriever rank">
        <span className="sr-only">Rank </span>
        {c ? c.rank + 1 : 'n/a'}
      </span>
      <div className="cand-main">
        <p className="memory-text cand-content">{c ? c.content : <code className="mono">{row.id}</code>}</p>
        <div className="cand-meta">
          {c && <SourceTags sources={c.sources} />}
          {c && (
            <span className="cand-score" title={scoreHint ?? 'Retriever score'}>
              score {fmtScore(c.score)}
            </span>
          )}
          {c && <span className="cand-date">{fmtDate(c.observed_at)}</span>}
          {!judged && c && c.status !== 'active' && (
            <ValidityChip validity={c.status} label={`Stored as ${c.status}`} />
          )}
        </div>
        {judged && j && (
          <div className="cand-judgment">
            <div className="cand-bars">
              <ScoreBar label="Relevance" value={j.relevance} threshold={read?.relevance} band={read?.band} />
              <ScoreBar label="Utility" value={j.utility} threshold={read?.utility} band={read?.band} />
            </div>
            <div className="cand-why">
              <Reason reason={j.reason} decision={j.decision} />
              <ValidityChip validity={j.validity} />
              <Annotations items={j.annotations} />
            </div>
          </div>
        )}
        {judged && !j && <p className="cand-why small muted">No judgment returned for this candidate.</p>}
        {flag}
      </div>
      <div className="cand-decision">
        {judged && j ? <DecisionBadge decision={j.decision} /> : <InjectedMark injected={row.injected} />}
      </div>
    </li>
  );
}

function Reason({ reason, decision }: { reason: string; decision: string }) {
  const r = rowReason(reason, decision);
  return (
    <span className="cand-reason" title={r.full ?? undefined}>
      {r.text}
    </span>
  );
}
