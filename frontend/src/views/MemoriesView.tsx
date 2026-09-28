import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  api,
  MEMORY_TYPES,
  type Lineage,
  type MemoryListItem,
  type MemoryLink,
  type MemoryType,
  type PublicConfig,
} from '../api';
import { EmptyState, ErrorNotice, Loading } from '../components/Notice';
import { ValidityChip } from '../components/Tags';
import { fmtDate, humanize, plural } from '../format';
import { useAction, useAsync } from '../hooks';
import { uniqueLinks } from '../recall';
import type { Navigate, Params } from '../route';
import { LineageTimeline } from './LineageTimeline';
import { ValidityTimeline } from './ValidityTimeline';
import './memories.css';

interface MemoriesViewProps {
  user: string;
  params: Params;
  navigate: Navigate;
  config: PublicConfig | undefined;
  /** Bumped by the app when memories change elsewhere (seed, reset, chat extraction). */
  version: number;
  onMemoriesChanged: () => void;
}

/** Lineage of every memory (small demo sets) so the timeline can draw hand-offs. */
const LINEAGE_FETCH_LIMIT = 80;

async function fetchLineages(ids: string[], signal: AbortSignal): Promise<Map<string, Lineage>> {
  const out = new Map<string, Lineage>();
  const queue = [...ids];
  const worker = async () => {
    while (queue.length > 0) {
      const id = queue.shift();
      if (!id || signal.aborted) return;
      try {
        out.set(id, await api.lineage(id, signal));
      } catch {
        /* a missing lineage only removes connectors; the table still renders */
      }
    }
  };
  await Promise.all(Array.from({ length: 4 }, worker));
  return out;
}

export function MemoriesView({ user, params, navigate, config, version, onMemoriesChanged }: MemoriesViewProps) {
  const selectedId = params.id;
  const [localVersion, setLocalVersion] = useState(0);
  const listKey = `${user}|${version}|${localVersion}`;
  const list = useAsync((signal) => api.memories(user, signal), listKey);
  const memories = list.data;
  const [serverNow, setServerNow] = useState(() => new Date());
  useEffect(() => setServerNow(new Date()), [memories]);

  const lineageIds = useMemo(() => {
    if (!memories) return [];
    const all = memories.map((m) => m.id);
    const ids =
      all.length <= LINEAGE_FETCH_LIMIT ? all : memories.filter((m) => m.status === 'superseded').map((m) => m.id);
    if (selectedId && !ids.includes(selectedId)) ids.push(selectedId);
    return ids;
  }, [memories, selectedId]);

  const lineages = useAsync(
    (signal) => fetchLineages(lineageIds, signal),
    memories ? `${listKey}|${lineageIds.join(',')}` : null,
  );

  const allLinks = useMemo<MemoryLink[]>(
    () => uniqueLinks([...(lineages.data?.values() ?? [])].flatMap((l) => l.links)),
    [lineages.data],
  );
  const byId = useMemo(() => new Map((memories ?? []).map((m) => [m.id, m])), [memories]);

  const panelRef = useRef<HTMLElement>(null);
  function select(id: string) {
    navigate({ params: { id } }, { replace: true });
    if (window.matchMedia?.('(max-width: 1399px)').matches) {
      window.requestAnimationFrame(() => panelRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
    }
  }

  function changed() {
    setLocalVersion((v) => v + 1);
    onMemoriesChanged();
  }

  const active = memories?.filter((m) => m.status !== 'archived').length ?? 0;

  return (
    <div className="memories-view">
      <div className="section-head mem-head">
        <h1 className="view-title">
          Memories <span className="count">for {user}</span>
        </h1>
        {memories && (
          <p className="small muted">
            {plural(memories.length, 'memory', 'memories')}, {active} not archived
          </p>
        )}
      </div>

      {list.error && <ErrorNotice error={list.error} onRetry={list.reload} />}
      {list.loading && !memories && <Loading>Loading memories</Loading>}

      {memories && memories.length === 0 && (
        <EmptyState title={`No memories for ${user} yet`}>
          Use <strong>Seed demo</strong> above to write the dated Alex demo memories through the write-time lifecycle,
          or add one below.
        </EmptyState>
      )}

      {memories && memories.length > 0 && (
        <section className="panel panel-pad vt-panel" aria-labelledby="vt-h">
          <div className="section-head">
            <h2 id="vt-h">Validity over time</h2>
            <span className="small muted">
              {lineages.loading ? 'Loading lineage links' : 'Select a row to open its lineage'}
            </span>
          </div>
          <ValidityTimeline
            memories={memories}
            links={allLinks}
            ttlDays={config?.policy.write.ttl_days}
            now={serverNow}
            selectedId={selectedId}
            onSelect={select}
          />
        </section>
      )}

      <div className="mem-grid">
        <div className="mem-main">
          {memories && memories.length > 0 && (
            <section className="panel mem-table-panel" aria-labelledby="mt-h">
              <div className="section-head panel-pad-x">
                <h2 id="mt-h">
                  All memories <span className="count">{memories.length}</span>
                </h2>
              </div>
              <MemoryTable memories={memories} selectedId={selectedId} onSelect={select} onArchived={changed} />
            </section>
          )}
          <AddMemory user={user} onAdded={changed} />
        </div>

        <aside className={`mem-side panel panel-pad${selectedId ? '' : ' is-empty'}`} ref={panelRef} aria-labelledby="lin-h">
          <div className="section-head">
            <h2 id="lin-h">Lineage</h2>
            {selectedId && (
              <button type="button" className="btn btn-sm btn-quiet" onClick={() => navigate({ params: { id: undefined } }, { replace: true })}>
                Close
              </button>
            )}
          </div>
          {selectedId ? (
            <LineagePanel id={selectedId} cached={lineages.data?.get(selectedId)} links={allLinks} byId={byId} onSelect={select} />
          ) : (
            <EmptyState title="Select a memory">
              Its lineage shows the supersession chain in date order, with each relation the judge recorded and its
              probability.
            </EmptyState>
          )}
        </aside>
      </div>
    </div>
  );
}

function LineagePanel({
  id,
  cached,
  links,
  byId,
  onSelect,
}: {
  id: string;
  cached: Lineage | undefined;
  links: MemoryLink[];
  byId: Map<string, MemoryListItem>;
  onSelect: (id: string) => void;
}) {
  const fresh = useAsync((signal) => api.lineage(id, signal), cached ? null : id);
  const lineage = cached ?? fresh.data;
  if (fresh.error) return <ErrorNotice error={fresh.error} onRetry={fresh.reload} />;
  if (!lineage) return <Loading>Loading lineage</Loading>;
  const chainSize = lineage.chain.length;
  return (
    <div className="lin-panel">
      <p className="small muted lin-summary">
        {chainSize > 1 ? `Supersession chain of ${chainSize}` : 'Not part of a supersession chain'}
        {lineage.conflicts.length > 0 ? `, ${plural(lineage.conflicts.length, 'conflict')}` : ''}
        {lineage.duplicates.length > 0 ? `, ${plural(lineage.duplicates.length, 'duplicate')}` : ''}
        {`, ${plural(lineage.links.length, 'recorded link')}`}
      </p>
      <LineageTimeline lineage={lineage} extraLinks={links} memoriesById={byId} onSelect={onSelect} />
    </div>
  );
}

function MemoryTable({
  memories,
  selectedId,
  onSelect,
  onArchived,
}: {
  memories: MemoryListItem[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onArchived: () => void;
}) {
  const sorted = useMemo(
    () => [...memories].sort((a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime()),
    [memories],
  );
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const archive = useAction(api.archiveMemory);

  async function doArchive(id: string) {
    setConfirmId(null);
    const out = await archive.run(id);
    if (out) onArchived();
  }

  return (
    <>
      {archive.error && (
        <div className="panel-pad-x">
          <ErrorNotice error={archive.error} onDismiss={archive.clearError} />
        </div>
      )}
      <div className="mem-table-wrap">
        <table className="mem-table">
          <thead>
            <tr>
              <th scope="col">Observed</th>
              <th scope="col">Memory</th>
              <th scope="col">Status</th>
              <th scope="col">Validity</th>
              <th scope="col">Durability</th>
              <th scope="col">Flags</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m) => (
              <tr key={m.id} className={`${selectedId === m.id ? 'is-selected' : ''}${m.status === 'archived' ? ' is-archived' : ''}`}>
                <td data-label="Observed" className="mt-date">
                  <time dateTime={m.observed_at}>{fmtDate(m.observed_at)}</time>
                </td>
                <td data-label="Memory" className="mt-content">
                  <button
                    type="button"
                    className="mt-open memory-text"
                    onClick={() => onSelect(m.id)}
                    aria-pressed={selectedId === m.id}
                  >
                    {m.content}
                  </button>
                  <span className="mt-type small muted">{humanize(m.memory_type)}</span>
                </td>
                <td data-label="Status">
                  <span className={`status-text status-${m.status}`}>{m.status}</span>
                </td>
                <td data-label="Validity">
                  <ValidityChip validity={m.validity} />
                </td>
                <td data-label="Durability" className="small">
                  {m.lifecycle_pending ? (
                    <span className="muted">pending</span>
                  ) : m.durability ? (
                    <>
                      {m.durability}
                      {m.horizon && <span className="muted"> ({m.horizon})</span>}
                    </>
                  ) : (
                    <span className="muted">not judged</span>
                  )}
                </td>
                <td data-label="Flags">
                  {m.instruction_like ? (
                    <span
                      className="flag-warn"
                      title="Judged at write time as text that tries to direct an AI. Kept for audit, never injected."
                    >
                      <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
                        <path d="M7 1.4 L12.9 12 H1.1 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                        <path d="M7 5.4 V8.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                        <circle cx="7" cy="10.1" r="0.8" fill="currentColor" />
                      </svg>
                      Instruction-like
                    </span>
                  ) : (
                    <span className="muted small">
                      none<span className="sr-only"> flagged</span>
                    </span>
                  )}
                </td>
                <td className="mt-actions">
                  {m.status === 'archived' ? (
                    <span className="small muted">Archived</span>
                  ) : confirmId === m.id ? (
                    <span className="mt-confirm">
                      <button type="button" className="btn btn-sm btn-danger" onClick={() => void doArchive(m.id)} disabled={archive.pending}>
                        Confirm archive
                      </button>
                      <button type="button" className="btn btn-sm btn-quiet" onClick={() => setConfirmId(null)}>
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setConfirmId(m.id)}
                      disabled={archive.pending}
                      aria-label={`Archive: ${m.content.slice(0, 60)}`}
                    >
                      Archive
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AddMemory({ user, onAdded }: { user: string; onAdded: () => void }) {
  const ids = useId();
  const [content, setContent] = useState('');
  const [type, setType] = useState<MemoryType>('other');
  const [observed, setObserved] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const create = useAction(api.createMemory);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    const text = content.trim();
    if (!text) return;
    const out = await create.run({
      user_id: user,
      content: text,
      memory_type: type,
      observed_at: observed ? new Date(`${observed}T12:00:00Z`).toISOString() : undefined,
    });
    if (out) {
      const links = out.relations.filter((r) => r.action).length;
      setDone(
        `Written as ${out.durability ?? 'unjudged'}${out.instruction_like ? ', flagged instruction-like' : ''}; ${plural(out.relations.length, 'neighbour')} judged, ${plural(links, 'link')} recorded.`,
      );
      setContent('');
      onAdded();
    }
  }

  return (
    <details className="panel add-memory">
      <summary className="panel-pad-x add-summary">Add a memory</summary>
      <form className="add-form panel-pad-x" onSubmit={onSubmit}>
        <div className="field add-content">
          <label htmlFor={`${ids}-c`}>Memory text</label>
          <textarea
            id={`${ids}-c`}
            className="textarea"
            rows={2}
            maxLength={4000}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="For example: I switched my phone plan to prepaid."
          />
        </div>
        <div className="field">
          <label htmlFor={`${ids}-t`}>Type</label>
          <select id={`${ids}-t`} className="select" value={type} onChange={(e) => setType(e.target.value as MemoryType)}>
            {MEMORY_TYPES.map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${ids}-o`}>Observed on</label>
          <input
            id={`${ids}-o`}
            className="input"
            type="date"
            value={observed}
            onChange={(e) => setObserved(e.target.value)}
            aria-describedby={`${ids}-o-hint`}
          />
        </div>
        <div className="add-actions">
          <button type="submit" className="btn btn-primary" disabled={create.pending || !content.trim()}>
            {create.pending ? 'Writing' : 'Add memory'}
          </button>
        </div>
        <p id={`${ids}-o-hint`} className="small muted add-hint">
          Leave the date empty to use now. Memories must be written in date order, so an older date than the newest
          memory is rejected.
        </p>
        {create.error && <ErrorNotice error={create.error} onDismiss={create.clearError} />}
        {done && (
          <p className="small add-done" role="status">
            {done}
          </p>
        )}
      </form>
    </details>
  );
}

