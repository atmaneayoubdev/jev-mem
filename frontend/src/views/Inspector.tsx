import type { Policy, RecallOutcome, WrittenMemory } from '../api';
import { CandidateRow } from '../components/CandidateRow';
import { DecisionBadge } from '../components/DecisionBadge';
import { IntentMeter, LatencyBar } from '../components/Meters';
import { EmptyState, FallbackDetail } from '../components/Notice';
import { Chip } from '../components/Tags';
import { fmtCost, fmtDate, fmtMs, humanize, plural } from '../format';
import {
  decisionTally,
  fallbackSummary,
  isJudgedMode,
  MODE_DESCRIPTION,
  modeLabel,
  recallRows,
  splitInjected,
  type TurnTrace,
} from '../recall';

const SCORE_HINT: Record<string, string> = {
  recency: 'Recency score',
  bm25: 'BM25 score',
  embedding: 'Cosine similarity',
  jev: 'BM25 score (first stage)',
  hybrid: 'Reciprocal-rank fusion of BM25, embedding and recency',
};

export function Inspector({ trace, policy }: { trace: TurnTrace | null; policy?: Policy }) {
  if (!trace) {
    return (
      <section className="inspector panel panel-pad" aria-label="Memory inspector">
        <h2 className="inspector-title">Memory inspector</h2>
        <EmptyState title="No turn selected yet">
          Send a message or pick a demo query. For each answer, this panel shows which memories were retrieved, how
          Jev judged them, and exactly what reached the model.
        </EmptyState>
      </section>
    );
  }

  const d = trace.debug;
  const latency = trace.latency ?? (d ? { retrieval: d.retrieval_ms, judge: d.judge_ms } : null);

  return (
    <section className="inspector panel panel-pad" aria-label="Memory inspector">
      {d ? (
        <TraceBody outcome={d} policy={policy} latency={latency} restored={!trace.latency} roundTripMs={trace.roundTripMs} />
      ) : (
        <>
          <h2 className="inspector-title">Memory inspector</h2>
          <div className="notice notice-info" role="note">
            <div className="notice-body">
              <p className="notice-title">Debug output is disabled on this server</p>
              <p className="notice-message">
                The answer used memory, but the server does not expose recall traces (<code>memory_debug</code> is
                null). Set <code>DEBUG_PAYLOADS=true</code> outside production to inspect candidates and judgments.
              </p>
            </div>
          </div>
          {latency && (
            <div className="insp-block">
              <h3>Latency</h3>
              <LatencyBar latency={latency} />
            </div>
          )}
        </>
      )}
      <Extracted items={trace.extracted} error={trace.extractionError} />
    </section>
  );
}

function TraceBody({
  outcome: d,
  policy,
  latency,
  restored,
  roundTripMs,
}: {
  outcome: RecallOutcome;
  policy?: Policy;
  latency: Partial<Record<'retrieval' | 'judge' | 'generation', number>> | null;
  /** Rebuilt from GET /conversations: no generation time or extracted memories. */
  restored: boolean;
  roundTripMs?: number;
}) {
  const judgedMode = isJudgedMode(d.mode);
  const rows = recallRows(d);
  const { injected, withheld } = splitInjected(rows);
  const tally = decisionTally(d);
  const scoreHint = SCORE_HINT[d.mode];

  return (
    <>
      <header className="insp-head">
        <h2 className="inspector-title">Memory inspector</h2>
        <p className="insp-query memory-text">
          <span className="sr-only">Query: </span>
          {d.query}
        </p>
        <p className="insp-sub small muted">
          <span>
            <strong className="insp-mode">{modeLabel(d.mode)}</strong> mode
          </span>
          <span>as of {fmtDate(d.now)}</span>
          <span>{plural(d.candidates.length, 'candidate')}</span>
        </p>
        <p className="insp-desc small muted">{(MODE_DESCRIPTION as Record<string, string>)[d.mode]}</p>
      </header>

      <dl className="insp-facts">
        <div className="fact">
          <dt>Intent</dt>
          <dd>
            {d.intent ? (
              <IntentMeter intent={d.intent} />
            ) : (
              <span className="muted">{judgedMode ? 'Not judged (judge unavailable)' : 'Not judged in baseline modes'}</span>
            )}
          </dd>
        </div>
        <div className="fact">
          <dt>Judge</dt>
          <dd>
            <JudgeFact outcome={d} />
          </dd>
        </div>
        <div className="fact">
          <dt>Context</dt>
          <dd>
            <strong>{plural(d.context_tokens, 'token')}</strong>
            <span className="muted"> from {plural(d.selected_ids.length, 'memory', 'memories')}</span>
          </dd>
        </div>
        {latency && (
          <div className="fact fact-wide">
            <dt>Latency</dt>
            <dd>
              <LatencyBar latency={latency} />
              {roundTripMs !== undefined && <RoundTrip ms={roundTripMs} latency={latency} />}
              {restored && (
                <p className="xsmall muted restored-note">
                  Restored from the saved conversation, which keeps the recall trace but not the generation time or
                  the memories extracted in this turn.
                </p>
              )}
            </dd>
          </div>
        )}
      </dl>

      {tally.length > 0 && (
        <ul className="tally" aria-label="Decisions">
          {tally.map((t) => (
            <li key={t.decision}>
              <DecisionBadge decision={t.decision} compact />
              <span className="tally-n">{t.count}</span>
            </li>
          ))}
        </ul>
      )}

      {judgedMode ? (
        <>
          <div className="insp-block">
            <div className="section-head">
              <h3>
                Injected into context <span className="count">{injected.length}</span>
              </h3>
              <span className="small muted">Selected by the policy and sent to the model</span>
            </div>
            {injected.length === 0 ? (
              <p className="small muted">Nothing was injected. The model answered without memories.</p>
            ) : (
              <ol className="cand-list">
                {injected.map((r) => (
                  <CandidateRow key={r.id} row={r} judged policy={policy} scoreHint={scoreHint} />
                ))}
              </ol>
            )}
          </div>
          <div className="insp-block">
            <div className="section-head">
              <h3>
                Withheld <span className="count">{withheld.length}</span>
              </h3>
              <span className="small muted">Retrieved but not sent to the model</span>
            </div>
            {withheld.length === 0 ? (
              <p className="small muted">Every candidate was injected.</p>
            ) : (
              <ol className="cand-list">
                {withheld.map((r) => (
                  <CandidateRow key={r.id} row={r} judged policy={policy} scoreHint={scoreHint} />
                ))}
              </ol>
            )}
          </div>
        </>
      ) : (
        <div className="insp-block">
          <div className="section-head">
            <h3>
              Ranked candidates <span className="count">{rows.length}</span>
            </h3>
            <span className="small muted">
              {injected.length} injected by rank alone
              {withheld.length > 0 ? `, ${withheld.length} cut by the token budget` : ''}
            </span>
          </div>
          <ol className="cand-list">
            {rows.map((r) => (
              <CandidateRow key={r.id} row={r} judged={false} scoreHint={scoreHint} />
            ))}
          </ol>
        </div>
      )}

      <details className="insp-block context-block">
        <summary>
          <span className="context-summary">Context sent to the model</span>
          <span className="muted small"> {plural(d.context_tokens, 'token')}</span>
        </summary>
        <p className="small muted context-note">
          Rendered memory block, placed in the system prompt after the assistant instructions.
        </p>
        <pre className="context-text">{d.context_text || '(empty: no memories were injected)'}</pre>
      </details>
    </>
  );
}

function RoundTrip({ ms, latency }: { ms: number; latency: Partial<Record<string, number>> }) {
  const reported = Object.values(latency).reduce<number>((a, b) => a + (b ?? 0), 0);
  return (
    <p className="xsmall muted restored-note">
      Round trip measured in the browser: <strong className="round-trip">{fmtMs(ms)}</strong>.
      {ms < reported * 0.8 &&
        ' Lower than the stage total because cached model responses report the latency measured when they were first computed.'}
    </p>
  );
}

function JudgeFact({ outcome: d }: { outcome: RecallOutcome }) {
  const cost = fmtCost(d.judge_cost);
  if (d.judge_used) {
    return (
      <span>
        <strong>Used</strong>
        <span className="muted">
          {' '}
          {plural(d.judge_calls, 'call')}, {fmtMs(d.judge_ms)}
          {cost ? `, ${cost}` : ''}
        </span>
      </span>
    );
  }
  if (isJudgedMode(d.mode)) {
    return (
      <div className="judge-fallback">
        <Chip tone="warn">Not used</Chip>
        <FallbackDetail summary={`${fallbackSummary(d.fallback_reason)}; candidates kept in retriever order`} raw={d.fallback_reason} />
      </div>
    );
  }
  return <span className="muted">Not used in {modeLabel(d.mode)} mode</span>;
}

function Extracted({ items, error }: { items: WrittenMemory[] | null; error: string | null }) {
  if (items === null && !error) return null;
  return (
    <div className="insp-block">
      <div className="section-head">
        <h3>
          Extracted from this turn <span className="count">{items?.length ?? 0}</span>
        </h3>
        <span className="small muted">New memories Qwen proposed, written through the lifecycle</span>
      </div>
      {error && (
        <div className="notice notice-warn" role="note">
          <div className="notice-body">
            <p className="notice-title">Extraction failed</p>
            <p className="notice-message">{error}</p>
          </div>
        </div>
      )}
      {items && items.length === 0 && !error && <p className="small muted">No new memories in this turn.</p>}
      {items && items.length > 0 && (
        <ul className="extracted">
          {items.map((w) => (
            <li key={w.memory.id} className="extracted-item">
              <p className="memory-text">{w.memory.content}</p>
              <p className="small muted extracted-meta">
                <span>{humanize(w.memory.memory_type)}</span>
                {w.durability && <span>{w.durability}</span>}
                <span>{plural(w.relations.length, 'relation')} judged</span>
                {w.instruction_like && <Chip tone="conflict">Instruction-like</Chip>}
                {w.pending && <Chip tone="warn">Lifecycle pending</Chip>}
                {w.error && <span>Error: {w.error}</span>}
              </p>
              {w.relations.filter((r) => r.action).length > 0 && (
                <ul className="extracted-rel small">
                  {w.relations
                    .filter((r) => r.action)
                    .map((r) => (
                      <li key={r.earlier_id}>
                        {humanize(r.action ?? '')} <code className="mono">{r.earlier_id.slice(0, 8)}</code>
                        <span className="muted"> ({r.reason})</span>
                      </li>
                    ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
