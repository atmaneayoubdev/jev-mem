import { describe, expect, it } from 'vitest';
import {
  DECISIONS,
  LINK_TYPES,
  MEMORY_STATUSES,
  MEMORY_TYPES,
  MODES,
  toApiError,
  VALIDITIES,
  type RecallOutcome,
} from '../api';
import { compareDisagreements, slotGroups, validityEnd } from '../recall';
import { benchmarkRuns, chat, compare, config, lineage, memories } from './fixtures';

function outcomes(): RecallOutcome[] {
  return [chat.memory_debug, ...Object.values(compare)].filter((o): o is RecallOutcome => o != null);
}

describe('fixtures fit the TypeScript contract', () => {
  it('uses only known modes, decisions, validities and statuses', () => {
    expect(config.modes.every((m) => (MODES as readonly string[]).includes(m))).toBe(true);
    for (const o of outcomes()) {
      expect(MODES).toContain(o.mode);
      expect(typeof o.context_tokens).toBe('number');
      for (const c of o.candidates) {
        expect(MEMORY_STATUSES).toContain(c.status);
        expect(Array.isArray(c.sources)).toBe(true);
      }
      for (const j of o.judgments) {
        expect(DECISIONS).toContain(j.decision);
        expect(VALIDITIES).toContain(j.validity);
      }
      // Every selected id is a candidate; selected and rejected partition the candidates.
      const ids = new Set(o.candidates.map((c) => c.id));
      for (const id of o.selected_ids) expect(ids.has(id)).toBe(true);
    }
    for (const m of memories) {
      expect(VALIDITIES).toContain(m.validity);
      expect(MEMORY_STATUSES).toContain(m.status);
      expect(MEMORY_TYPES).toContain(m.memory_type);
    }
    for (const l of lineage.links) expect(LINK_TYPES).toContain(l.link_type);
    for (const r of benchmarkRuns) expect(typeof r.run_id).toBe('string');
  });
});

describe('toApiError', () => {
  it('reads the backend {error, message, request_id} shape', () => {
    const e = toApiError(503, {
      error: 'service_unavailable',
      message: 'Qwen is not configured: set QWEN_BASE_URL and QWEN_MODEL',
      request_id: 'abc',
    });
    expect(e.status).toBe(503);
    expect(e.code).toBe('service_unavailable');
    expect(e.message).toBe('Qwen is not configured: set QWEN_BASE_URL and QWEN_MODEL');
    expect(e.requestId).toBe('abc');
  });

  it('reads FastAPI {detail} strings and validation lists', () => {
    expect(toApiError(422, { detail: "judge needs mode 'jev' or 'hybrid'" }).message).toBe(
      "judge needs mode 'jev' or 'hybrid'",
    );
    const v = toApiError(422, { detail: [{ loc: ['body', 'message'], msg: 'Field required' }] });
    expect(v.code).toBe('validation_error');
    expect(v.message).toBe('message: Field required');
  });

  it('explains a missing backend behind the dev proxy', () => {
    const e = toApiError(502, undefined, 'Bad Gateway');
    expect(e.code).toBe('backend_unreachable');
    expect(e.message).toMatch(/port 8765/);
    expect(toApiError(429, { error: 'rate_limited' }).message).toMatch(/Too many requests/);
  });
});

describe('recall derivations', () => {
  const byId = new Map(memories.map((m) => [m.id, m]));

  it('ends a superseded memory where its first successor begins, and expires temporary ones by TTL', () => {
    const aws = byId.get('d560e2a5429a413cacc741c34dbd78b4');
    const riyadh = byId.get('28b9571c594f4484b9e6e8c4ba2facd9');
    if (!aws || !riyadh) throw new Error('fixture memories missing');
    const awsEnd = validityEnd(aws, lineage.links, byId, config.policy.write.ttl_days);
    expect(awsEnd?.kind).toBe('superseded');
    expect(awsEnd?.at.toISOString()).toBe('2026-08-05T10:00:00.000Z');
    const riyadhEnd = validityEnd(riyadh, [], byId, config.policy.write.ttl_days);
    expect(riyadhEnd?.kind).toBe('expires');
    // observed 4 May + 42 days ("weeks" horizon)
    expect(riyadhEnd?.at.toISOString()).toBe('2026-06-15T10:00:00.000Z');
  });

  it('groups a supersession chain into one slot', () => {
    const groups = slotGroups(memories, lineage.links);
    const cloud = groups.find((g) => g.some((m) => m.id === 'd560e2a5429a413cacc741c34dbd78b4'));
    // links in the fixture: migration -> AWS, Azure -> AWS (Priya's link is uncertain)
    expect(cloud?.map((m) => m.observed_at.slice(0, 10))).toEqual(['2026-01-06', '2026-08-05', '2026-09-14']);
  });

  it('lists baseline-injected memories the judged mode withheld, in baseline rank order', () => {
    const [d] = compareDisagreements(compare, ['embedding', 'hybrid']);
    expect(d?.withheld.map((w) => w.baselineRank)).toEqual([0, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(d?.withheld[0]?.judgment?.decision).toBe('stale');
    expect(d?.added).toHaveLength(0);
  });
});
