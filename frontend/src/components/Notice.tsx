import type { ReactNode } from 'react';
import type { ApiError } from '../api';

/** Shows the backend's `{error, message}` cleanly, with status and request id for bug reports. */
export function ErrorNotice({
  error,
  title,
  onRetry,
  onDismiss,
}: {
  error: ApiError;
  title?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div className="notice notice-error" role="alert">
      <div className="notice-body">
        <p className="notice-title">{title ?? headline(error)}</p>
        <p className="notice-message">{error.message}</p>
        <p className="notice-meta">
          <span>{error.status ? `HTTP ${error.status}` : 'No response'}</span>
          <code>{error.code}</code>
          {error.requestId && <span>request {error.requestId}</span>}
        </p>
      </div>
      {(onRetry || onDismiss) && (
        <div className="notice-actions">
          {onRetry && (
            <button type="button" className="btn btn-sm" onClick={onRetry}>
              Try again
            </button>
          )}
          {onDismiss && (
            <button type="button" className="btn btn-sm btn-quiet" onClick={onDismiss}>
              Dismiss
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function headline(error: ApiError): string {
  if (error.status === 503) return 'A required model is unavailable';
  if (error.status === 404) return 'Not found';
  if (error.status === 409) return 'Rejected by the memory store';
  if (error.status === 422) return 'The request was not accepted';
  if (error.status === 429) return 'Rate limited';
  if (error.status === 403) return 'Not allowed on this server';
  if (error.status === 0 || error.code === 'backend_unreachable') return 'Cannot reach the JevMem API';
  return 'Request failed';
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function Loading({ children }: { children: ReactNode }) {
  return (
    <p className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {children}
    </p>
  );
}

/** The judge's fallback reason: a short summary with the raw provider text on demand. */
export function FallbackDetail({ summary, raw }: { summary: string; raw: string | null }) {
  return (
    <div className="fallback-detail">
      <span>{summary}</span>
      {raw && raw !== summary && (
        <details className="fallback-raw">
          <summary>Error text</summary>
          <code>{raw}</code>
        </details>
      )}
    </div>
  );
}
