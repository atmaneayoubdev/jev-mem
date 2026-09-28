import { useEffect, useId, useState } from 'react';
import { api } from '../api';
import { useAction, useElapsed } from '../hooks';
import { ErrorNotice } from './Notice';

interface SessionBarProps {
  user: string;
  users: string[];
  onUser: (u: string) => void;
  asOf: string | undefined;
  onAsOf: (d: string | undefined) => void;
  /** Called after seed or reset so views can refetch. */
  onDataChanged: (kind: 'seed' | 'reset') => void;
}

export function SessionBar({ user, users, onUser, asOf, onAsOf, onDataChanged }: SessionBarProps) {
  const ids = useId();
  const [status, setStatus] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const seed = useAction(api.seedDemo);
  const reset = useAction(api.resetDemo);
  const busy = seed.pending || reset.pending;
  const elapsed = useElapsed(seed.pending);

  useEffect(() => {
    if (!confirmReset) return;
    const t = window.setTimeout(() => setConfirmReset(false), 6000);
    return () => window.clearTimeout(t);
  }, [confirmReset]);

  const options = users.includes(user) ? users : [user, ...users];

  async function doSeed() {
    setStatus(null);
    reset.clearError();
    const out = await seed.run(user);
    if (out) {
      setStatus(`Seeded ${out.memories.length} memories for ${out.user_id}.`);
      onDataChanged('seed');
    }
  }

  async function doReset() {
    setConfirmReset(false);
    setStatus(null);
    seed.clearError();
    const out = await reset.run(user);
    if (out) {
      setStatus(`Reset ${out.user_id}: removed ${out.removed} records.`);
      onDataChanged('reset');
    }
  }

  const error = seed.error ?? reset.error;

  return (
    <section className="session" aria-label="Demo session">
      <div className="page session-inner">
        <div className="field">
          <label htmlFor={`${ids}-user`}>User</label>
          <select
            id={`${ids}-user`}
            className="select"
            value={user}
            onChange={(e) => onUser(e.target.value)}
            disabled={busy}
          >
            {options.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor={`${ids}-asof`}>As of</label>
          <div className="asof">
            <input
              id={`${ids}-asof`}
              className="input"
              type="date"
              value={asOf ?? ''}
              onChange={(e) => onAsOf(e.target.value || undefined)}
              aria-describedby={`${ids}-asof-hint`}
            />
            {asOf && (
              <button type="button" className="btn btn-sm btn-quiet" onClick={() => onAsOf(undefined)}>
                Use today
              </button>
            )}
          </div>
          <span id={`${ids}-asof-hint`} className="sr-only">
            Time travel: chat and compare judge validity as if today were this date.
          </span>
        </div>

        <p className="session-hint small muted" aria-hidden={asOf ? undefined : true}>
          {asOf
            ? 'Chat and compare judge validity as of this date.'
            : 'Set a date to replay recall as of that day.'}
        </p>

        <div className="session-actions">
          <button type="button" className="btn" onClick={doSeed} disabled={busy}>
            {seed.pending ? `Seeding (${elapsed}s)` : 'Seed demo'}
          </button>
          {confirmReset ? (
            <>
              <button type="button" className="btn btn-danger" onClick={doReset} disabled={busy}>
                Confirm reset
              </button>
              <button type="button" className="btn btn-quiet" onClick={() => setConfirmReset(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn"
              onClick={() => setConfirmReset(true)}
              disabled={busy}
              aria-describedby={`${ids}-reset-hint`}
            >
              {reset.pending ? 'Resetting' : 'Reset demo'}
            </button>
          )}
          <span id={`${ids}-reset-hint`} className="sr-only">
            Deletes all memories and conversations for this user.
          </span>
        </div>
      </div>
      <div className="page">
        <p className="session-status small" role="status" aria-live="polite">
          {seed.pending
            ? 'Writing the demo memories in date order through the write-time lifecycle, where Jev judges each one. This can take 20 seconds or more.'
            : confirmReset
              ? `Reset deletes every memory and conversation for ${user}.`
              : (status ?? '')}
        </p>
        {error && (
          <ErrorNotice
            error={error}
            onDismiss={() => {
              seed.clearError();
              reset.clearError();
            }}
          />
        )}
      </div>
    </section>
  );
}
