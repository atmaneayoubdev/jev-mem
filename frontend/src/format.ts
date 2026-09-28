/** Display formatting. Dates are shown in UTC so fixture and server dates never shift. */

// Fixed month names: Intl month abbreviations differ between ICU versions ("Sep" / "Sept").
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function toDate(v: string | Date): Date {
  return typeof v === 'string' ? new Date(v) : v;
}

const intFmt = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });

export function fmtDate(iso: string | Date | null | undefined): string {
  if (!iso) return '';
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function fmtShortDate(iso: string | Date): string {
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function fmtMonth(d: Date): string {
  return MONTHS[d.getUTCMonth()] ?? '';
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return 'n/a';
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  return `${intFmt.format(ms)} ms`;
}

/** Scores differ in scale by retriever (cosine, BM25, reciprocal-rank fusion): 3 significant digits. */
export function fmtScore(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n === 0) return '0';
  return Math.abs(n) >= 1000 ? intFmt.format(n) : n.toPrecision(3);
}

export function fmtProb(p: number | null | undefined): string {
  return p === null || p === undefined ? 'n/a' : p.toFixed(2);
}

export function fmtPct(x: number, digits = 1): string {
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtCost(usd: number | null | undefined): string | null {
  if (usd === null || usd === undefined) return null;
  return `$${usd.toPrecision(3)}`;
}

export function fmtInt(n: number): string {
  return intFmt.format(n);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

export function humanize(s: string): string {
  return s.replace(/_/g, ' ');
}

export function truncate(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n - 1).trimEnd()}…`;
}
