import { useEffect, useState } from 'react';
import { api } from './api';
import { Header } from './components/Header';
import { ErrorNotice } from './components/Notice';
import { SessionBar } from './components/SessionBar';
import { useAsync } from './hooks';
import { useRoute, VIEW_LABEL } from './route';
import { BenchmarkView } from './views/BenchmarkView';
import { ChatView } from './views/ChatView';
import { CompareView } from './views/CompareView';
import { MemoriesView } from './views/MemoriesView';

const DEFAULT_USER = 'alex';
const HEALTH_POLL_MS = 30_000;

export function App() {
  const [route, navigate] = useRoute();
  const [healthTick, setHealthTick] = useState(0);
  const [usersVersion, setUsersVersion] = useState(0);
  const [memVersion, setMemVersion] = useState(0);
  const [resetCount, setResetCount] = useState(0);

  const config = useAsync((s) => api.config(s), 'config');
  const health = useAsync((s) => api.health(s), `health-${healthTick}`);
  const users = useAsync((s) => api.users(s), `users-${usersVersion}`);
  const demo = useAsync((s) => api.demoQueries(s), 'demo');

  useEffect(() => {
    const t = window.setInterval(() => setHealthTick((n) => n + 1), HEALTH_POLL_MS);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    document.title = `${VIEW_LABEL[route.view]}, JevMem`;
  }, [route.view]);

  const user = route.params.u ?? DEFAULT_USER;
  const asOf = route.params.t && /^\d{4}-\d{2}-\d{2}$/.test(route.params.t) ? route.params.t : undefined;
  // The as-of override is sent as midday UTC on the chosen date.
  const now = asOf ? `${asOf}T12:00:00Z` : undefined;
  const demoQueries = demo.data ?? [];

  function onDataChanged() {
    setMemVersion((v) => v + 1);
    setUsersVersion((v) => v + 1);
    // Seed also resets the user first, so the old conversation is gone either way.
    setResetCount((n) => n + 1);
    navigate({ params: { c: undefined, id: undefined } }, { replace: true });
  }

  const apiDown = config.error ?? null;

  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          // The hash is the router's; move focus instead of navigating.
          e.preventDefault();
          document.getElementById('main')?.focus();
        }}
      >
        Skip to content
      </a>
      <Header route={route} health={health.data} config={config.data} healthError={health.error} />
      <SessionBar
        user={user}
        users={users.data ?? []}
        onUser={(u) => navigate({ params: { u, c: undefined, id: undefined } }, { replace: true })}
        asOf={asOf}
        onAsOf={(t) => navigate({ params: { t } }, { replace: true })}
        onDataChanged={onDataChanged}
      />
      <main id="main" className="page main" tabIndex={-1}>
        {apiDown && (
          <div className="app-error">
            <ErrorNotice
              error={apiDown}
              title="Cannot load the server configuration"
              onRetry={() => {
                config.reload();
                setHealthTick((n) => n + 1);
              }}
            />
          </div>
        )}
        {route.view === 'chat' && (
          <ChatView
            key={`${user}|${resetCount}`}
            user={user}
            params={route.params}
            navigate={navigate}
            config={config.data}
            demoQueries={demoQueries}
            now={now}
            onMemoriesChanged={() => setMemVersion((v) => v + 1)}
          />
        )}
        {route.view === 'compare' && (
          <CompareView
            key={user}
            user={user}
            params={route.params}
            navigate={navigate}
            config={config.data}
            demoQueries={demoQueries}
            now={now}
          />
        )}
        {route.view === 'memories' && (
          <MemoriesView
            key={user}
            user={user}
            params={route.params}
            navigate={navigate}
            config={config.data}
            version={memVersion}
            onMemoriesChanged={() => setUsersVersion((v) => v + 1)}
          />
        )}
        {route.view === 'benchmark' && <BenchmarkView params={route.params} navigate={navigate} />}
      </main>
    </>
  );
}
