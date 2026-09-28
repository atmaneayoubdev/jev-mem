/** Pure derivations over API payloads: shared by views and tests. */

import {
  JUDGED_MODES,
  type CandidateView,
  type ChatResponse,
  type CompareResponse,
  type Decision,
  type JudgmentView,
  type LatencyMs,
  type LinkType,
  type Memory,
  type MemoryLink,
  type Mode,
  type RecallOutcome,
  type Validity,
  type WrittenMemory,
} from './api';

// --- modes --------------------------------------------------------------------

export const MODE_LABEL: Record<Mode, string> = {
  recency: 'Recency',
  bm25: 'BM25',
  embedding: 'Embedding',
  jev: 'Jev',
  hybrid: 'Hybrid',
};

export const MODE_DESCRIPTION: Record<Mode, string> = {
  recency: 'Newest memories first. No judge: the top results go straight into context.',
  bm25: 'Keyword match (BM25). No judge: the top results go straight into context.',
  embedding: 'Vector similarity. No judge: the top results go straight into context.',
  jev: 'BM25 candidates, judged by Jev, decided by the policy.',
  hybrid: 'BM25, embedding and recency candidates, judged by Jev, decided by the policy.',
};

export function modeLabel(mode: string): string {
  return (MODE_LABEL as Record<string, string>)[mode] ?? mode;
}

export function isJudgedMode(mode: string): boolean {
  return JUDGED_MODES.has(mode as Mode);
}

// --- decisions ----------------------------------------------------------------

export interface DecisionMeta {
  label: string;
  /** Whether the policy injects this decision into the model context (by default). */
  injected: boolean;
  description: string;
}

export const DECISION_META: Record<Decision, DecisionMeta> = {
  use: { label: 'Use', injected: true, description: 'Relevant and useful now: injected into the context.' },
  conflict: {
    label: 'Conflict',
    injected: true,
    description: 'Injected together with the memory it contradicts, flagged as conflicting.',
  },
  unjudged: {
    label: 'Unjudged',
    injected: true,
    description: 'Judge unavailable: kept in retriever order, never a faked judgment.',
  },
  keep: { label: 'Keep', injected: false, description: 'Relevant but not useful for this query: not injected.' },
  stale: {
    label: 'Stale',
    injected: false,
    description: 'Superseded, expired or overridden, and the query is about the present: not injected.',
  },
  uncertain: {
    label: 'Uncertain',
    injected: false,
    description: 'Inside the uncertainty band around the thresholds: not injected.',
  },
  drop: { label: 'Drop', injected: false, description: 'Not relevant, archived or instruction-like: not injected.' },
};

export function decisionMeta(decision: string): DecisionMeta {
  return (
    (DECISION_META as Record<string, DecisionMeta>)[decision] ?? {
      label: decision,
      injected: false,
      description: decision,
    }
  );
}

// --- validity / status ----------------------------------------------------------

export const VALIDITY_LABEL: Record<Validity, string> = {
  current: 'Current',
  superseded: 'Superseded',
  expired: 'Expired',
  overridden: 'Overridden',
  archived: 'Archived',
};

/** Lineage node state: ACTIVE / SUPERSEDED / EXPIRED / OVERRIDDEN / ARCHIVED, in sentence case. */
export function nodeStateLabel(validity: Validity | undefined, status: string): string {
  if (validity) return validity === 'current' ? 'Active' : VALIDITY_LABEL[validity];
  if (status === 'active') return 'Active';
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function sourceLabel(source: string): string {
  return source.startsWith('link:') ? `link: ${source.slice(5)}` : source;
}

// --- judge fallback ---------------------------------------------------------------

/** A short, readable summary of a raw fallback reason (provider errors can be long JSON). */
export function fallbackSummary(reason: string | null | undefined): string {
  if (!reason) return 'Judge unavailable';
  const status = /\(HTTP (\d{3})\)/.exec(reason)?.[1];
  if (/not configured/i.test(reason)) return 'Jev is not configured';
  if (/circuit/i.test(reason)) return 'Judge circuit open';
  if (status) return `Judge call failed (HTTP ${status})`;
  return reason.length > 80 ? 'Judge call failed' : reason;
}

/** Row-level reason for a fallback decision, shortened when it only repeats the column's reason. */
export function rowReason(reason: string, decision: string): { text: string; full: string | null } {
  if (!reason.startsWith('fallback:')) return { text: reason, full: null };
  const text =
    decision === 'unjudged'
      ? 'Judge unavailable: kept in retriever order'
      : 'Judge unavailable: below the fallback cut-off';
  return { text, full: reason };
}

// --- recall rows ------------------------------------------------------------------

export interface RecallRow {
  id: string;
  candidate: CandidateView | null;
  judgment: JudgmentView | null;
  injected: boolean;
}

/** Candidates joined with judgments, in retriever rank order. */
export function recallRows(outcome: RecallOutcome): RecallRow[] {
  const judgments = new Map(outcome.judgments.map((j) => [j.id, j]));
  const selected = new Set(outcome.selected_ids);
  const rows: RecallRow[] = [...outcome.candidates]
    .sort((a, b) => a.rank - b.rank)
    .map((c) => ({ id: c.id, candidate: c, judgment: judgments.get(c.id) ?? null, injected: selected.has(c.id) }));
  // A selected id that is not a candidate (should not happen, but never hide what was injected).
  const known = new Set(rows.map((r) => r.id));
  for (const id of outcome.selected_ids) {
    if (!known.has(id)) rows.push({ id, candidate: null, judgment: judgments.get(id) ?? null, injected: true });
  }
  return rows;
}

export function splitInjected(rows: RecallRow[]): { injected: RecallRow[]; withheld: RecallRow[] } {
  return { injected: rows.filter((r) => r.injected), withheld: rows.filter((r) => !r.injected) };
}

export function decisionTally(outcome: RecallOutcome): { decision: Decision; count: number }[] {
  const counts = new Map<Decision, number>();
  for (const j of outcome.judgments) counts.set(j.decision, (counts.get(j.decision) ?? 0) + 1);
  const order: Decision[] = ['use', 'conflict', 'unjudged', 'stale', 'uncertain', 'keep', 'drop'];
  return order.filter((d) => counts.has(d)).map((d) => ({ decision: d, count: counts.get(d) ?? 0 }));
}

// --- chat traces ------------------------------------------------------------------

/** Everything the inspector shows for one assistant turn. */
export interface TurnTrace {
  debug: RecallOutcome | null;
  latency: LatencyMs | null;
  extracted: WrittenMemory[] | null;
  extractionError: string | null;
  /** Wall-clock time of the /chat request measured in the browser, if known. */
  roundTripMs?: number;
}

export function traceFromChat(resp: ChatResponse, roundTripMs?: number): TurnTrace {
  return {
    debug: resp.memory_debug,
    latency: resp.latency_ms,
    extracted: resp.extracted,
    extractionError: resp.extraction_error,
    roundTripMs,
  };
}

// --- compare ------------------------------------------------------------------------

export interface CompareDisagreement {
  baseline: Mode;
  judged: Mode;
  /** Injected by the similarity baseline, withheld by the judged mode. */
  withheld: { row: RecallRow; baselineRank: number; judgment: JudgmentView | null }[];
  /** Injected by the judged mode, not injected by the baseline. */
  added: { row: RecallRow; judgment: JudgmentView | null }[];
}

export function orderedModes(results: CompareResponse, order: readonly Mode[]): Mode[] {
  const present = Object.keys(results) as Mode[];
  const known = order.filter((m) => present.includes(m));
  return [...known, ...present.filter((m) => !known.includes(m))];
}

export function compareDisagreements(results: CompareResponse, modes: readonly Mode[]): CompareDisagreement[] {
  const out: CompareDisagreement[] = [];
  const baselines = modes.filter((m) => !isJudgedMode(m) && results[m]);
  const judged = modes.filter((m) => isJudgedMode(m) && results[m]);
  for (const b of baselines) {
    const base = results[b];
    if (!base) continue;
    const baseRows = recallRows(base);
    const baseSelected = new Set(base.selected_ids);
    for (const j of judged) {
      const jr = results[j];
      if (!jr) continue;
      const jRows = new Map(recallRows(jr).map((r) => [r.id, r]));
      const jSelected = new Set(jr.selected_ids);
      const withheld = baseRows
        .filter((r) => r.injected && !jSelected.has(r.id))
        .map((r) => ({
          row: jRows.get(r.id) ?? r,
          baselineRank: r.candidate ? r.candidate.rank : -1,
          judgment: jRows.get(r.id)?.judgment ?? null,
        }));
      const added = [...jRows.values()]
        .filter((r) => r.injected && !baseSelected.has(r.id))
        .map((r) => ({ row: r, judgment: r.judgment }));
      out.push({ baseline: b, judged: j, withheld, added });
    }
  }
  return out;
}

// --- lineage ------------------------------------------------------------------------

export const LINK_LABEL: Record<LinkType, string> = {
  supersedes: 'supersedes',
  temporarily_overrides: 'temporarily overrides',
  conflicts_with: 'conflicts with',
  reinforces: 'reinforces',
  refines: 'refines',
  uncertain_relation: 'uncertain relation to',
};

/** Which judge probability backs each link type (see WritePolicy.pair). */
const LINK_PROBABILITY_KEY: Record<LinkType, string | null> = {
  supersedes: 'supersedes',
  temporarily_overrides: 'supersedes',
  conflicts_with: 'contradicts',
  reinforces: 'duplicate',
  refines: 'refines',
  uncertain_relation: null,
};

export function linkLabel(type: string): string {
  return (LINK_LABEL as Record<string, string>)[type] ?? type.replace(/_/g, ' ');
}

/** The judge's probability for the relation the link records (top choice for uncertain links). */
export function linkProbability(link: MemoryLink): { relation: string; p: number } | null {
  const key = (LINK_PROBABILITY_KEY as Record<string, string | null>)[link.link_type] ?? null;
  if (key !== null && typeof link.probabilities[key] === 'number') {
    return { relation: key, p: link.probabilities[key] };
  }
  const top = topProbabilities(link, 1)[0];
  return top ? { relation: top[0], p: top[1] } : null;
}

export function topProbabilities(link: MemoryLink, n: number): [string, number][] {
  return Object.entries(link.probabilities)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

export function uniqueLinks(links: Iterable<MemoryLink>): MemoryLink[] {
  const seen = new Map<string, MemoryLink>();
  for (const l of links) if (!seen.has(l.id)) seen.set(l.id, l);
  return [...seen.values()];
}

export function byObserved<T extends Pick<Memory, 'observed_at' | 'sequence' | 'id'>>(a: T, b: T): number {
  const d = new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime();
  if (d !== 0) return d;
  if (a.sequence !== b.sequence) return a.sequence - b.sequence;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/**
 * When a memory stops being valid, from what the API returns: the first memory that superseded
 * it, an explicit `valid_until`, or (for temporary memories) observed_at + the policy TTL.
 */
export function validityEnd(
  memory: Memory,
  links: readonly MemoryLink[],
  memoriesById: ReadonlyMap<string, Memory>,
  ttlDays: Record<string, number> | undefined,
): { at: Date; kind: 'superseded' | 'expires' } | null {
  const successors = links
    .filter((l) => l.link_type === 'supersedes' && l.target_id === memory.id)
    .map((l) => memoriesById.get(l.source_id))
    .filter((m): m is Memory => m !== undefined)
    .map((m) => new Date(m.observed_at).getTime());
  if (memory.status === 'superseded' && successors.length > 0) {
    return { at: new Date(Math.min(...successors)), kind: 'superseded' };
  }
  if (memory.valid_until) return { at: new Date(memory.valid_until), kind: 'expires' };
  if (memory.durability === 'temporary' && ttlDays) {
    const days = ttlDays[memory.horizon ?? 'weeks'];
    if (typeof days === 'number') {
      return { at: new Date(new Date(memory.observed_at).getTime() + days * 86_400_000), kind: 'expires' };
    }
  }
  return null;
}

/** Groups memories that describe the same slot (supersession, override, conflict, reinforcement). */
export function slotGroups<T extends Memory>(memories: readonly T[], links: readonly MemoryLink[]): T[][] {
  const parent = new Map<string, string>(memories.map((m) => [m.id, m.id]));
  const find = (x: string): string => {
    let r = x;
    while (parent.get(r) !== r) r = parent.get(r) ?? r;
    parent.set(x, r);
    return r;
  };
  const SLOT: ReadonlySet<string> = new Set(['supersedes', 'temporarily_overrides', 'conflicts_with', 'reinforces']);
  for (const l of links) {
    if (!SLOT.has(l.link_type) || !parent.has(l.source_id) || !parent.has(l.target_id)) continue;
    const a = find(l.source_id);
    const b = find(l.target_id);
    if (a !== b) parent.set(a, b);
  }
  const groups = new Map<string, T[]>();
  for (const m of memories) {
    const root = find(m.id);
    const g = groups.get(root) ?? [];
    g.push(m);
    groups.set(root, g);
  }
  const list = [...groups.values()].map((g) => [...g].sort(byObserved));
  return list.sort((a, b) => byObserved(a[0] as T, b[0] as T));
}
