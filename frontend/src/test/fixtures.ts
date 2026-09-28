/**
 * Real API responses captured from the running backend (frontend/fixtures/*.json), typed.
 * `contract.test.ts` checks that their enum values fit the TypeScript unions in `api.ts`.
 */
import type {
  BenchmarkRun,
  ChatResponse,
  CompareResponse,
  DemoQuery,
  Health,
  Lineage,
  MemoryListItem,
  MetricsSummary,
  PublicConfig,
} from '../api';
import benchmarkJson from '../../fixtures/benchmark_runs.json';
import chatJson from '../../fixtures/chat.json';
import compareJson from '../../fixtures/compare.json';
import configJson from '../../fixtures/config_public.json';
import demoJson from '../../fixtures/demo_queries.json';
import healthJson from '../../fixtures/health.json';
import lineageJson from '../../fixtures/memory_lineage.json';
import memoriesJson from '../../fixtures/memories.json';
import metricsJson from '../../fixtures/metrics_summary.json';
import usersJson from '../../fixtures/users.json';

const as = <T,>(v: unknown) => v as T;

export const chat = as<ChatResponse>(chatJson);
export const compare = as<CompareResponse>(compareJson);
export const config = as<PublicConfig>(configJson);
export const lineage = as<Lineage>(lineageJson);
export const memories = as<MemoryListItem[]>(memoriesJson);
export const benchmarkRuns = as<BenchmarkRun[]>(benchmarkJson);
export const demoQueries = as<DemoQuery[]>(demoJson);
export const health = as<Health>(healthJson);
export const metrics = as<MetricsSummary>(metricsJson);
export const users = as<string[]>(usersJson);
