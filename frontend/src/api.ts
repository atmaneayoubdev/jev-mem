/**
 * Typed client for the JevMem REST API (v1).
 *
 * Types mirror the FastAPI responses captured in `frontend/fixtures/*.json`
 * (see `src/jevmem/api/routes/core.py`, `src/jevmem/memory/service.py`).
 */

export const API_BASE = '/api/v1';

// --- enums ------------------------------------------------------------------

export const MODES = ['recency', 'bm25', 'embedding', 'jev', 'hybrid'] as const;
export type Mode = (typeof MODES)[number];

/** Modes that run the Jev judge and the deterministic read policy. */
export const JUDGED_MODES: ReadonlySet<Mode> = new Set<Mode>(['jev', 'hybrid']);

export const DECISIONS = ['use', 'keep', 'drop', 'stale', 'conflict', 'uncertain', 'unjudged'] as const;
export type Decision = (typeof DECISIONS)[number];

export const VALIDITIES = ['current', 'superseded', 'expired', 'overridden', 'archived'] as const;
export type Validity = (typeof VALIDITIES)[number];

export const MEMORY_STATUSES = ['active', 'superseded', 'archived'] as const;
export type MemoryStatus = (typeof MEMORY_STATUSES)[number];

export const LINK_TYPES = [
  'supersedes',
  'temporarily_overrides',
  'conflicts_with',
  'reinforces',
  'refines',
  'uncertain_relation',
] as const;
export type LinkType = (typeof LINK_TYPES)[number];

export const MEMORY_TYPES = [
  'profile',
  'preference',
  'fact',
  'goal',
  'constraint',
  'decision',
  'event',
  'relationship',
  'work_context',
  'temporary_state',
  'other',
] as const;
export type MemoryType = (typeof MEMORY_TYPES)[number];

export type Durability = 'lasting' | 'temporary' | 'event';
export type Horizon = 'days' | 'weeks' | 'months' | 'year';
export type IntentKind = 'current' | 'historical' | 'both';

// --- system -------------------------------------------------------------------

export interface Health {
  status: string;
  version: string;
  jev_configured: boolean;
  qwen_configured: boolean;
  embeddings: boolean;
  /** Circuit-breaker state per provider, with the last error when it opened. */
  circuit: Record<string, CircuitState>;
}

export interface CircuitState {
  state: 'closed' | 'open' | 'half-open';
  last_error: string | null;
}

export interface ReadThresholds {
  relevance: number;
  utility: number;
  band: number;
  intent_confidence: number;
}

export interface Policy {
  version: string;
  read: ReadThresholds;
  write: {
    relation: number;
    confidence: number;
    instruction: number;
    ttl_days: Record<string, number>;
  };
  ablation: Record<string, boolean>;
  inject_uncertain: boolean;
  supersede_mode: string;
}

export interface PublicConfig {
  settings: Record<string, unknown>;
  modes: Mode[];
  default_mode: Mode;
  question_schema_version: string;
  policy_version: string;
  policy: Policy;
  debug_payloads: boolean;
}

export interface DemoQuery {
  query: string;
  demonstrates: string;
}

// --- recall -------------------------------------------------------------------

export interface CandidateView {
  id: string;
  content: string;
  /** Which retrievers produced it: bm25, embedding, recency, link:successor, ... */
  sources: string[];
  score: number;
  rank: number;
  observed_at: string;
  status: MemoryStatus;
}

export interface JudgmentView {
  id: string;
  relevance: number | null;
  utility: number | null;
  decision: Decision;
  reason: string;
  validity: Validity;
  historical: boolean;
  annotations: string[];
}

export interface IntentView {
  intent: IntentKind;
  low_confidence: boolean;
  judged: IntentKind | null;
  probabilities: Partial<Record<IntentKind, number>> | null;
}

export interface RecallOutcome {
  mode: Mode;
  query: string;
  now: string;
  candidates: CandidateView[];
  judgments: JudgmentView[];
  selected_ids: string[];
  rejected_ids: string[];
  intent: IntentView | null;
  judge_used: boolean;
  fallback_reason: string | null;
  context_text: string;
  context_tokens: number;
  retrieval_ms: number;
  judge_ms: number;
  judge_calls: number;
  judge_cost: number | null;
}

export interface RetrieveResponse {
  mode: Mode;
  candidates: CandidateView[];
}

export type CompareResponse = Partial<Record<Mode, RecallOutcome>>;

// --- memories -----------------------------------------------------------------

export interface Memory {
  id: string;
  user_id: string;
  session_id: string | null;
  content: string;
  normalized_content: string | null;
  memory_type: MemoryType;
  created_at: string;
  observed_at: string;
  sequence: number;
  valid_from: string | null;
  valid_until: string | null;
  source_turn_id: string | null;
  status: MemoryStatus;
  durability: Durability | null;
  horizon: Horizon | null;
  lifecycle_pending: boolean;
  instruction_like: boolean;
  confidence: number | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

/** `GET /memories` adds the validity computed against the server's current time. */
export interface MemoryListItem extends Memory {
  validity: Validity;
}

export interface MemoryLink {
  id: string;
  link_type: LinkType;
  /** The later memory. */
  source_id: string;
  /** The earlier memory. */
  target_id: string;
  probabilities: Record<string, number>;
  confidence: number | null;
  judge: string;
  question_schema_version: string | null;
  policy_version: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface Lineage {
  memory: Memory;
  validity: Validity;
  chain: Memory[];
  duplicates: Memory[];
  conflicts: Memory[];
  links: MemoryLink[];
}

export interface WrittenRelation {
  earlier_id: string;
  relation: string;
  probabilities: Record<string, number>;
  action: string | null;
  reason: string;
}

export interface WrittenMemory {
  memory: Memory;
  durability: string | null;
  instruction_like: boolean;
  neighbors: string[];
  relations: WrittenRelation[];
  pending: boolean;
  error: string | null;
}

export interface MemoryCreate {
  user_id: string;
  content: string;
  memory_type?: MemoryType;
  observed_at?: string;
}

// --- chat ---------------------------------------------------------------------

export interface LatencyMs {
  retrieval: number;
  judge: number;
  generation: number;
}

export interface ChatRequest {
  user_id: string;
  message: string;
  conversation_id?: string;
  mode?: Mode;
  now?: string;
  extract?: boolean;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  extracted: WrittenMemory[];
  extraction_error: string | null;
  latency_ms: LatencyMs;
  /** Null when the server does not expose debug payloads (production). */
  memory_debug: RecallOutcome | null;
}

export interface ConversationTurn {
  id: string;
  role: string;
  content: string;
  created_at: string;
  retrieval_mode: Mode | null;
  debug: RecallOutcome | null;
}

// --- demo, benchmark, metrics -------------------------------------------------

export interface SeedResponse {
  user_id: string;
  memories: WrittenMemory[];
}

export interface ResetResponse {
  user_id: string;
  removed: number;
}

export interface BenchmarkRun {
  run_id: string;
  /** Mean answer correctness per system. Absent for runs still in progress. */
  answer_accuracy?: Record<string, number>;
  state?: string;
  started?: string;
  error?: string;
}

export interface LatencyStat {
  count: number;
  mean: number;
  p50: number;
  p95: number;
}

export interface ClientStats {
  requests: number;
  cache_hits: number;
  retries: number;
  errors: number;
  latency_ms_total: number;
  status_counts: Record<string, number>;
}

export interface MetricsSummary {
  service: {
    counters: Record<string, number>;
    latency_ms: Record<string, LatencyStat>;
  };
  clients: Record<string, ClientStats>;
}

// --- errors -------------------------------------------------------------------

/**
 * A failed request. The backend answers errors as `{error, message, request_id}`;
 * FastAPI validation and HTTP errors use `{detail}`; the rate limiter `{error}` only.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

const FRIENDLY: Record<string, string> = {
  rate_limited: 'Too many requests in the last minute. Wait a few seconds and try again.',
  request_too_large: 'The request is larger than the server accepts.',
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Turn an error response body into an ApiError. Exported for tests. */
export function toApiError(status: number, body: unknown, rawText = ''): ApiError {
  if (isRecord(body)) {
    const requestId = typeof body.request_id === 'string' ? body.request_id : null;
    if (typeof body.error === 'string') {
      const message =
        typeof body.message === 'string' ? body.message : (FRIENDLY[body.error] ?? body.error);
      return new ApiError(status, body.error, message, requestId);
    }
    if (typeof body.detail === 'string') {
      return new ApiError(status, `http_${status}`, body.detail, requestId);
    }
    if (Array.isArray(body.detail)) {
      const parts = body.detail.map((d) => {
        if (!isRecord(d)) return String(d);
        const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : '';
        const msg = typeof d.msg === 'string' ? d.msg : 'invalid';
        return loc ? `${loc}: ${msg}` : msg;
      });
      return new ApiError(status, 'validation_error', parts.join('; '), requestId);
    }
  }
  if (status >= 500 && !rawText.trim().startsWith('{')) {
    return new ApiError(
      status,
      'backend_unreachable',
      `The API did not answer (HTTP ${status}). Is the JevMem server running on port 8765?`,
    );
  }
  return new ApiError(status, `http_${status}`, rawText.slice(0, 300) || `HTTP ${status}`);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? { Accept: 'application/json' } : { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, 'network_error', 'Could not reach the API. Check that the JevMem server is running.');
  }
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }
  if (!res.ok) throw toApiError(res.status, parsed, text);
  return parsed as T;
}

const enc = encodeURIComponent;

export const api = {
  health: (signal?: AbortSignal) => request<Health>('GET', '/health', undefined, signal),
  config: (signal?: AbortSignal) => request<PublicConfig>('GET', '/config/public', undefined, signal),
  users: (signal?: AbortSignal) => request<string[]>('GET', '/users', undefined, signal),
  demoQueries: (signal?: AbortSignal) => request<DemoQuery[]>('GET', '/demo/queries', undefined, signal),
  seedDemo: (userId: string) => request<SeedResponse>('POST', '/demo/seed', { user_id: userId }),
  resetDemo: (userId: string) => request<ResetResponse>('POST', '/demo/reset', { user_id: userId }),

  chat: (body: ChatRequest, signal?: AbortSignal) => request<ChatResponse>('POST', '/chat', body, signal),
  conversation: (id: string, signal?: AbortSignal) =>
    request<ConversationTurn[]>('GET', `/conversations/${enc(id)}`, undefined, signal),

  memories: (userId: string, signal?: AbortSignal) =>
    request<MemoryListItem[]>('GET', `/memories?user_id=${enc(userId)}`, undefined, signal),
  lineage: (id: string, signal?: AbortSignal) => request<Lineage>('GET', `/memories/${enc(id)}`, undefined, signal),
  archiveMemory: (id: string) => request<Memory>('DELETE', `/memories/${enc(id)}`),
  createMemory: (body: MemoryCreate) => request<WrittenMemory>('POST', '/memories', body),

  compare: (body: { user_id: string; query: string; modes: Mode[]; now?: string }, signal?: AbortSignal) =>
    request<CompareResponse>('POST', '/compare', body, signal),
  judge: (body: { user_id: string; query: string; mode?: Mode; now?: string }, signal?: AbortSignal) =>
    request<RecallOutcome>('POST', '/judge', body, signal),
  retrieve: (body: { user_id: string; query: string; mode?: Mode }, signal?: AbortSignal) =>
    request<RetrieveResponse>('POST', '/retrieve', body, signal),

  metrics: (signal?: AbortSignal) => request<MetricsSummary>('GET', '/metrics/summary', undefined, signal),
  benchmarkRuns: (signal?: AbortSignal) => request<BenchmarkRun[]>('GET', '/benchmark/runs', undefined, signal),
};
