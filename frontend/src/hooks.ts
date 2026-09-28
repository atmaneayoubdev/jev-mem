import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { ApiError } from './api';

export interface AsyncState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

function asApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(0, 'client_error', err instanceof Error ? err.message : String(err));
}

/** Runs `fn` when `key` changes (and on reload). Aborts the previous run. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, key: string | null): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(key !== null);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (key === null) {
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fnRef
      .current(ctrl.signal)
      .then((d) => {
        if (!ctrl.signal.aborted) setData(d);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(asApiError(err));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** A one-shot action (POST etc.) with pending and error state. */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const run = useCallback(async (...args: A): Promise<T | undefined> => {
    setPending(true);
    setError(null);
    try {
      return await fnRef.current(...args);
    } catch (err) {
      setError(asApiError(err));
      return undefined;
    } finally {
      setPending(false);
    }
  }, []);
  return { run, pending, error, clearError: () => setError(null) };
}

/** Seconds elapsed while `active` is true (for long-running requests). */
export function useElapsed(active: boolean): number {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!active) {
      setSecs(0);
      return;
    }
    const start = Date.now();
    const t = window.setInterval(() => setSecs(Math.floor((Date.now() - start) / 1000)), 500);
    return () => window.clearInterval(t);
  }, [active]);
  return secs;
}

export interface AnchorRect {
  key: string;
  group: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
  cy: number;
}

/**
 * Measures elements marked `data-anchor="<key>"` (and optional `data-group`) inside `container`,
 * relative to it. Re-measures on resize and after web fonts load. Used for the SVG connectors
 * drawn over HTML layouts (compare threads, lineage arcs, timeline hand-offs).
 */
export function useAnchorRects(container: RefObject<HTMLElement | null>, deps: unknown[]): {
  rects: AnchorRect[];
  width: number;
  height: number;
} {
  const [state, setState] = useState<{ rects: AnchorRect[]; width: number; height: number }>({
    rects: [],
    width: 0,
    height: 0,
  });

  const measure = useCallback(() => {
    const root = container.current;
    if (!root) return;
    const base = root.getBoundingClientRect();
    const rects: AnchorRect[] = [];
    root.querySelectorAll<HTMLElement>('[data-anchor]').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      rects.push({
        key: el.dataset.anchor ?? '',
        group: el.dataset.group ?? '',
        left: r.left - base.left,
        right: r.right - base.left,
        top: r.top - base.top,
        bottom: r.bottom - base.top,
        cy: r.top - base.top + r.height / 2,
      });
    });
    const next = { rects, width: base.width, height: base.height };
    setState((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, [container]);

  useLayoutEffect(() => {
    measure();
  }, deps); // callers pass the data the layout depends on

  useEffect(() => {
    const root = container.current;
    if (!root) return;
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
    ro?.observe(root);
    window.addEventListener('resize', schedule);
    void document.fonts?.ready.then(schedule);
    return () => {
      cancelAnimationFrame(frame);
      ro?.disconnect();
      window.removeEventListener('resize', schedule);
    };
  }, [container, measure]);

  return state;
}
