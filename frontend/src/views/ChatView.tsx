import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { api, ApiError, type DemoQuery, type Mode, type PublicConfig } from '../api';
import { JudgeMarker, QueryChips, SegmentedControl } from '../components/Controls';
import { ErrorNotice } from '../components/Notice';
import { RichText } from '../components/RichText';
import { fmtDate } from '../format';
import { useElapsed } from '../hooks';
import { isJudgedMode, MODE_DESCRIPTION, modeLabel, traceFromChat, type TurnTrace } from '../recall';
import type { Navigate, Params } from '../route';
import { Inspector } from './Inspector';
import './chat.css';

interface UserTurn {
  role: 'user';
  id: string;
  content: string;
}

interface AssistantTurn {
  role: 'assistant';
  id: string;
  content: string;
  mode: string | null;
  asOf: string | null;
  trace: TurnTrace;
}

type Turn = UserTurn | AssistantTurn;

interface ChatViewProps {
  user: string;
  params: Params;
  navigate: Navigate;
  config: PublicConfig | undefined;
  demoQueries: DemoQuery[];
  /** ISO datetime for the as-of override, if set. */
  now: string | undefined;
  onMemoriesChanged: () => void;
}

let localId = 0;
const nextId = () => `local-${++localId}`;

export function ChatView({ user, params, navigate, config, demoQueries, now, onMemoriesChanged }: ChatViewProps) {
  const ids = useId();
  const modes = config?.modes ?? [];
  const mode = (params.m && modes.includes(params.m as Mode) ? params.m : (config?.default_mode ?? 'hybrid')) as Mode;
  const conversationId = params.c;

  const [turns, setTurns] = useState<Turn[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [extract, setExtract] = useState(true);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [restoring, setRestoring] = useState(false);
  const elapsed = useElapsed(pending !== null);
  const logRef = useRef<HTMLOListElement>(null);
  const restoredFor = useRef<string | null>(null);

  // Restore a conversation from the URL (e.g. after a reload).
  useEffect(() => {
    if (!conversationId || turns.length > 0 || restoredFor.current === conversationId) return;
    const ctrl = new AbortController();
    setRestoring(true);
    api
      .conversation(conversationId, ctrl.signal)
      .then((history) => {
        if (ctrl.signal.aborted) return;
        restoredFor.current = conversationId;
        const restored: Turn[] = history.map((t) =>
          t.role === 'assistant'
            ? {
                role: 'assistant',
                id: t.id,
                content: t.content,
                mode: t.retrieval_mode,
                asOf: t.debug?.now ?? null,
                trace: { debug: t.debug, latency: null, extracted: null, extractionError: null },
              }
            : { role: 'user', id: t.id, content: t.content },
        );
        setTurns(restored);
      })
      .catch(() => undefined)
      .finally(() => setRestoring(false));
    return () => ctrl.abort();
  }, [conversationId, turns.length]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, pending]);

  const assistantTurns = turns.filter((t): t is AssistantTurn => t.role === 'assistant');
  const selected =
    assistantTurns.find((t) => t.id === selectedId) ?? assistantTurns[assistantTurns.length - 1] ?? null;

  async function send(message: string) {
    const text = message.trim();
    if (!text || pending) return;
    setError(null);
    setPending(text);
    setDraft('');
    const userTurn: UserTurn = { role: 'user', id: nextId(), content: text };
    setTurns((t) => [...t, userTurn]);
    const started = performance.now();
    try {
      const resp = await api.chat({
        user_id: user,
        message: text,
        conversation_id: conversationId,
        mode,
        now,
        extract,
      });
      const reply: AssistantTurn = {
        role: 'assistant',
        id: nextId(),
        content: resp.answer,
        mode: resp.memory_debug?.mode ?? mode,
        asOf: now ?? null,
        trace: traceFromChat(resp, performance.now() - started),
      };
      setTurns((t) => [...t, reply]);
      setSelectedId(reply.id);
      restoredFor.current = resp.conversation_id;
      if (resp.conversation_id !== conversationId) navigate({ params: { c: resp.conversation_id } }, { replace: true });
      if (resp.extracted.length > 0) onMemoriesChanged();
    } catch (err) {
      // The turn was not stored by the server: take it back out and restore the draft.
      setTurns((t) => t.filter((x) => x.id !== userTurn.id));
      setDraft(text);
      setError(err instanceof ApiError ? err : new ApiError(0, 'client_error', String(err)));
    } finally {
      setPending(null);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(draft);
    }
  }

  function newConversation() {
    setTurns([]);
    setSelectedId(null);
    setError(null);
    restoredFor.current = null;
    navigate({ params: { c: undefined } }, { replace: true });
  }

  return (
    <div className="chat-view">
      <div className="chat-toolbar panel">
        <div className="chat-toolbar-row">
          {modes.length > 0 && (
            <SegmentedControl<Mode>
              legend="Retrieval mode"
              options={modes.map((m) => ({
                value: m,
                label: modeLabel(m),
                marker: isJudgedMode(m) ? <JudgeMarker /> : undefined,
              }))}
              value={mode}
              onChange={(m) => navigate({ params: { m } }, { replace: true })}
              disabled={pending !== null}
              describedBy={`${ids}-mode-desc`}
            />
          )}
          <label className="check extract-toggle">
            <input type="checkbox" checked={extract} onChange={(e) => setExtract(e.target.checked)} />
            Extract new memories from my messages
          </label>
        </div>
        <p id={`${ids}-mode-desc`} className="mode-desc small muted">
          <JudgeMarker /> marks judged modes. {modeLabel(mode)}: {MODE_DESCRIPTION[mode]}
        </p>
        <QueryChips queries={demoQueries} onPick={(q) => void send(q.query)} disabled={pending !== null} />
      </div>

      <div className="chat-grid">
        <section className="chat-panel panel" aria-label="Conversation">
          <div className="chat-panel-head">
            <h2>
              Conversation <span className="count">with {user}</span>
            </h2>
            {turns.length > 0 && (
              <button type="button" className="btn btn-sm btn-quiet" onClick={newConversation} disabled={pending !== null}>
                New conversation
              </button>
            )}
          </div>

          <ol className="chat-log" ref={logRef} aria-live="polite" aria-busy={pending !== null}>
            {turns.length === 0 && !pending && (
              <li className="chat-empty">
                {restoring
                  ? 'Loading the conversation.'
                  : `Ask something that depends on what ${user} has told the assistant before, or pick a demo query above. Select any answer to trace it in the inspector.`}
              </li>
            )}
            {turns.map((t) =>
              t.role === 'user' ? (
                <li key={t.id} className="turn turn-user">
                  <span className="sr-only">You: </span>
                  <p>{t.content}</p>
                </li>
              ) : (
                <li key={t.id} className="turn turn-assistant">
                  <div
                    className={`turn-card${selected?.id === t.id ? ' is-selected' : ''}`}
                    onClick={() => setSelectedId(t.id)}
                  >
                    <span className="sr-only">Assistant: </span>
                    <RichText text={t.content} />
                    <div className="turn-meta">
                      {t.mode && <span>{modeLabel(t.mode)}</span>}
                      {t.asOf && <span>as of {fmtDate(t.asOf)}</span>}
                      <button
                        type="button"
                        className="turn-inspect"
                        aria-pressed={selected?.id === t.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedId(t.id);
                        }}
                      >
                        {selected?.id === t.id ? 'Shown in inspector' : 'Inspect this answer'}
                      </button>
                    </div>
                  </div>
                </li>
              ),
            )}
            {pending && (
              <li className="turn turn-pending" role="status">
                <span className="spinner" aria-hidden="true" />
                {isJudgedMode(mode) ? 'Retrieving, judging and answering' : 'Retrieving and answering'} ({elapsed}s)
              </li>
            )}
          </ol>

          {error && (
            <div className="chat-error">
              <ErrorNotice error={error} onRetry={() => void send(draft)} onDismiss={() => setError(null)} />
            </div>
          )}

          <form className="composer" onSubmit={onSubmit}>
            <label htmlFor={`${ids}-msg`} className="sr-only">
              Message
            </label>
            <textarea
              id={`${ids}-msg`}
              className="textarea composer-input"
              rows={2}
              value={draft}
              maxLength={8000}
              placeholder={`Message as ${user}. Enter sends, Shift+Enter adds a line.`}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={pending !== null}
            />
            <button type="submit" className="btn btn-primary" disabled={pending !== null || !draft.trim()}>
              Send
            </button>
          </form>
        </section>

        <Inspector trace={selected?.trace ?? null} policy={config?.policy} />
      </div>
    </div>
  );
}
