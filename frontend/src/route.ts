/**
 * URL-hash state: `#/<view>?u=alex&m=hybrid&t=2026-06-01&...`.
 * Views and their parameters survive reloads and can be shared as links.
 */

import { useCallback, useEffect, useState } from 'react';

export const VIEWS = ['chat', 'compare', 'memories', 'benchmark'] as const;
export type View = (typeof VIEWS)[number];

export const VIEW_LABEL: Record<View, string> = {
  chat: 'Chat and inspector',
  compare: 'Compare',
  memories: 'Memories',
  benchmark: 'Benchmark',
};

/**
 * Known parameters. u: user, t: as-of date (YYYY-MM-DD), m: chat mode, c: conversation id,
 * q: compare query, cm: compare modes (comma list), id: memory id, run: benchmark run.
 */
export type ParamKey = 'u' | 't' | 'm' | 'c' | 'q' | 'cm' | 'id' | 'run';
export type Params = Partial<Record<ParamKey, string>>;

export interface Route {
  view: View;
  params: Params;
}

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '');
  const [path = '', query = ''] = raw.split('?', 2);
  const view = (VIEWS as readonly string[]).includes(path) ? (path as View) : 'chat';
  const params: Params = {};
  new URLSearchParams(query).forEach((value, key) => {
    if (value) params[key as ParamKey] = value;
  });
  return { view, params };
}

export function buildHash(route: Route): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(route.params)) if (v) qs.set(k, v);
  const s = qs.toString();
  return `#/${route.view}${s ? `?${s}` : ''}`;
}

export type Navigate = (patch: { view?: View; params?: Params }, opts?: { replace?: boolean }) => void;

export function useRoute(): [Route, Navigate] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const navigate = useCallback<Navigate>((patch, opts) => {
    const current = parseHash(window.location.hash);
    const next: Route = {
      view: patch.view ?? current.view,
      params: { ...current.params, ...patch.params },
    };
    const hash = buildHash(next);
    if (hash === window.location.hash) return;
    // replaceState/pushState do not fire hashchange, so update React state directly.
    if (opts?.replace) window.history.replaceState(null, '', hash);
    else window.history.pushState(null, '', hash);
    setRoute(parseHash(hash));
  }, []);

  return [route, navigate];
}
