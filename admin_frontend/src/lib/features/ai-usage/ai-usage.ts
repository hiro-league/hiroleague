/**
 * Logs → AI usage (Phase 7b): what every AI question adds up to over time — the extensions'
 * questions (ai.ask) and Hiro's own jobs (the graph ledger), counted by the core per hour.
 *
 * Pure sums over hourly rows. Each row is one hour × one combination of the dimensions below; the
 * page groups by ONE dimension and filters on any of the others (HomeHiro's LLM usage page could
 * only split by one and pick a single row, which made "only Home, only API, by model" impossible).
 * Ported from HomeHiro's `features/logs/usage/usage.ts`; times follow the 12-hour, say-the-day rule.
 */

export type Billing = 'api' | 'plan' | 'local';
export type Result = 'ok' | 'fell back' | 'failed';

export interface UsageRow {
  hour: number; // the hour's start, epoch ms
  kind: string; // what the call was: a question, speech, transcription, an image, embeddings
  source: string; // "Hiro" (the core's own jobs) or the extension's name ("Home")
  use: string; // the job or the extension use: "Chat", "Ask a camera"…
  profile: string;
  provider: string;
  model: string;
  billing: Billing;
  person: string | null; // the family member the call was for (Phase 6's people), when there is one
  label: string | null; // what the asker named it (a camera, a task), when it sends one
  result: Result;
  requests: number;
  tokensIn: number;
  tokensOut: number;
  ms: number; // summed
  cost: number; // USD billed (API keys)
  estimate: number; // USD a plan's requests would cost on an API key
  unpriced: number; // answered calls counted at $0: no price for the model, or no token counts to work one out
}

/** What the page can group by and filter on. */
export type Dimension = 'kind' | 'source' | 'use' | 'person' | 'profile' | 'provider' | 'model' | 'billing' | 'label' | 'result';

export const DIMENSIONS: { value: Dimension; label: string; plural: string }[] = [
  { value: 'kind', label: 'Kind', plural: 'All kinds' },
  { value: 'source', label: 'Source', plural: 'All sources' },
  { value: 'use', label: 'Use', plural: 'All uses' },
  // A defined dimension (not a label): the core knows the family, so "what each person costs" is reliable.
  { value: 'person', label: 'Person', plural: 'Everyone' },
  { value: 'profile', label: 'AI profile', plural: 'All profiles' },
  { value: 'provider', label: 'Provider', plural: 'All providers' },
  { value: 'model', label: 'Model', plural: 'All models' },
  { value: 'billing', label: 'Paid by', plural: 'Any payer' },
  { value: 'label', label: 'Label', plural: 'All labels' },
  { value: 'result', label: 'Result', plural: 'Any result' }
];

export const BILLING: Record<Billing, string> = { api: 'API key', plan: 'Your plans', local: 'Home PC' };
export const NO_LABEL = 'No label';
export const NO_PERSON = 'No one';

export type Filters = Partial<Record<Dimension, string[]>>; // an empty or missing list = everything

export function keyOf(row: UsageRow, d: Dimension): string {
  if (d === 'billing') return BILLING[row.billing];
  if (d === 'label') return row.label ?? NO_LABEL;
  if (d === 'person') return row.person ?? NO_PERSON;
  if (d === 'use') return row.source === 'Hiro' ? row.use : `${row.use} (${row.source})`;
  return row[d];
}

export const applyFilters = (rows: UsageRow[], f: Filters) =>
  rows.filter((r) => DIMENSIONS.every(({ value: d }) => !f[d]?.length || f[d]!.includes(keyOf(r, d))));

/** The values a dimension takes in the rows (for its filter's checklist), the most requests first. */
export function valuesOf(rows: UsageRow[], d: Dimension): { value: string; count: number }[] {
  const by = new Map<string, number>();
  for (const r of rows) by.set(keyOf(r, d), (by.get(keyOf(r, d)) ?? 0) + r.requests);
  return [...by].map(([value, count]) => ({ value, count })).sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

// ── Days and bars ───────────────────────────────────────────────────────────────────────────────

export type Period = 'today' | 'yesterday' | '7d' | '30d' | '90d';
export type Step = 'hour' | 'day' | 'week';
export type Metric = 'requests' | 'cost' | 'tokens' | 'time';

export const PERIODS: { value: Period; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' }
];
export const STEPS: { value: Step; label: string }[] = [
  { value: 'hour', label: 'Hours' },
  { value: 'day', label: 'Days' },
  { value: 'week', label: 'Weeks' }
];
export const METRICS: { value: Metric; label: string }[] = [
  { value: 'requests', label: 'Calls' },
  { value: 'cost', label: 'Cost' },
  { value: 'tokens', label: 'Tokens' },
  { value: 'time', label: 'Time' }
];

export interface Span {
  from: number; // a midnight
  to: number; // the midnight after the last day
}
export interface Range extends Span {
  step: Step;
}

export const HOUR = 3_600_000;
const DAY = 86_400_000;
export const midnight = (t: number, days = 0) => {
  const d = new Date(t);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days).getTime();
};
export const daysIn = (s: Span) => Math.round((s.to - s.from) / DAY);

export function spanOf(period: Period, now: number): Span {
  const today = midnight(now);
  const back = { today: 0, yesterday: 1, '7d': 6, '30d': 29, '90d': 89 }[period];
  return { from: midnight(today, -back), to: period === 'yesterday' ? today : midnight(today, 1) };
}
export const periodOf = (s: Span, now: number): Period | null =>
  PERIODS.find((p) => {
    const x = spanOf(p.value, now);
    return x.from === s.from && x.to === s.to;
  })?.value ?? null;

export function stepsFor(s: Span): Step[] {
  const n = daysIn(s);
  return STEPS.map((x) => x.value).filter((x) => (x === 'hour' ? n <= 7 : x === 'day' ? n >= 2 && n <= 180 : n >= 14));
}
export const autoStep = (s: Span): Step => (daysIn(s) <= 2 ? 'hour' : daysIn(s) <= 62 ? 'day' : 'week');

export function shiftSpan(s: Span, dir: -1 | 1, now: number): Span | null {
  const n = daysIn(s);
  const out = { from: midnight(s.from, dir * n), to: midnight(s.to, dir * n) };
  return out.from > midnight(now) ? null : out;
}

/** The same span just before; a span still running is compared up to the same time of day. */
export function previous(r: Range, now: number): Range {
  const from = midnight(r.from, -daysIn(r));
  return { from, to: r.to > now ? from + (now - r.from) : r.from, step: r.step };
}
export function previousLabel(s: Span, now: number): string {
  const n = daysIn(s);
  if (n === 1) return s.to > now ? 'yesterday by this time' : 'the day before';
  return `the ${n} days before${s.to > now ? ' by this time' : ''}`;
}

export function bucketStarts(r: Range): number[] {
  const out: number[] = [];
  for (let t = r.from; t < r.to; ) {
    out.push(t);
    t = r.step === 'hour' ? t + HOUR : r.step === 'day' ? midnight(t, 1) : midnight(t, 7 - ((new Date(t).getDay() + 6) % 7));
  }
  return out;
}
export const inRange = (rows: UsageRow[], r: Span) => rows.filter((x) => x.hour >= r.from && x.hour < r.to);

// ── People read these: 12-hour clock, always the day ────────────────────────────────────────────

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "1 PM", "12 AM". */
export function hourLabel(t: number): string {
  const h = new Date(t).getHours();
  return `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`;
}
/** "Nov 9" (with the year when it isn't this year). */
export function shortDate(t: number, now: number): string {
  const d = new Date(t);
  const year = d.getFullYear() !== new Date(now).getFullYear() ? `, ${d.getFullYear()}` : '';
  return `${MONTH[d.getMonth()]} ${d.getDate()}${year}`;
}
/** "Today", "Yesterday", "Mon, Nov 9". */
export function dayLabel(t: number, now: number): string {
  const m = midnight(t);
  if (m === midnight(now)) return 'Today';
  if (m === midnight(now, -1)) return 'Yesterday';
  return `${WEEKDAY[new Date(t).getDay()]}, ${shortDate(t, now)}`;
}
export function spanLabel(s: Span, now: number): string {
  if (daysIn(s) === 1) return dayLabel(s.from, now);
  return `${shortDate(s.from, now)} – ${shortDate(midnight(s.to, -1), now)}`;
}

// ── Sums ────────────────────────────────────────────────────────────────────────────────────────

export function valueOf(row: UsageRow, metric: Metric): number {
  switch (metric) {
    case 'requests':
      return row.requests;
    case 'cost':
      return row.cost + row.estimate;
    case 'tokens':
      return row.tokensIn + row.tokensOut;
    case 'time':
      return row.ms / 1000;
  }
}

export interface Totals {
  requests: number;
  billed: number;
  estimate: number;
  unpriced: number; // answered calls counted at $0 (neither billed nor estimated), as HomeHiro's page showed
  unpricedModels: string[];
  plan: number;
  local: number;
  tokensIn: number;
  tokensOut: number;
  failed: number;
  fellBack: number;
  ms: number;
}

export function totals(rows: UsageRow[]): Totals {
  const t: Totals = { requests: 0, billed: 0, estimate: 0, unpriced: 0, unpricedModels: [], plan: 0, local: 0, tokensIn: 0, tokensOut: 0, failed: 0, fellBack: 0, ms: 0 };
  const unpriced = new Set<string>();
  for (const r of rows) {
    if (r.unpriced) {
      t.unpriced += r.unpriced;
      unpriced.add(r.model);
    }
    t.requests += r.requests;
    t.billed += r.cost;
    t.estimate += r.estimate;
    if (r.billing === 'plan') t.plan += r.requests;
    if (r.billing === 'local') t.local += r.requests;
    t.tokensIn += r.tokensIn;
    t.tokensOut += r.tokensOut;
    if (r.result === 'failed') t.failed += r.requests;
    if (r.result === 'fell back') t.fellBack += r.requests;
    t.ms += r.ms;
  }
  t.unpricedModels = [...unpriced].sort();
  return t;
}

export interface Group extends Totals {
  key: string;
}

export function groups(rows: UsageRow[], d: Dimension): Group[] {
  const by = new Map<string, UsageRow[]>();
  for (const r of rows) {
    const k = keyOf(r, d);
    const list = by.get(k);
    if (list) list.push(r);
    else by.set(k, [r]);
  }
  return [...by].map(([key, list]) => ({ key, ...totals(list) })).sort((a, b) => b.requests - a.requests || a.key.localeCompare(b.key));
}

export const OTHER = 'Everything else';

export interface Bars {
  keys: string[];
  bars: { start: number; values: Record<string, number>; total: number }[];
  max: number;
}

export function bars(rows: UsageRow[], r: Range, d: Dimension, metric: Metric, top = 6): Bars {
  const sums = new Map<string, number>();
  for (const row of rows) sums.set(keyOf(row, d), (sums.get(keyOf(row, d)) ?? 0) + valueOf(row, metric));
  const ranked = [...sums].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k);
  const shown = ranked.length > top ? ranked.slice(0, top - 1) : ranked;
  const keys = ranked.length > top ? [...shown, OTHER] : shown;
  const starts = bucketStarts(r);
  const out = starts.map((start) => ({ start, values: {} as Record<string, number>, total: 0 }));
  for (const row of rows) {
    let i = starts.length - 1;
    while (i > 0 && starts[i] > row.hour) i--;
    const bar = out[i];
    if (!bar) continue;
    const k = shown.includes(keyOf(row, d)) ? keyOf(row, d) : OTHER;
    const v = valueOf(row, metric);
    bar.values[k] = (bar.values[k] ?? 0) + v;
    bar.total += v;
  }
  return { keys, bars: out, max: Math.max(0, ...out.map((b) => b.total)) };
}

export const change = (now: number, before: number) => (before > 0 ? Math.round(((now - before) / before) * 100) : null);

export function short(n: number): string {
  if (n < 1e5) return String(Math.round(n)).replace(/\B(?=(\d{3})+$)/g, ',');
  if (n < 1e6) return `${Math.round(n / 1e3)}K`;
  return `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)}M`;
}
// A tiny real amount keeps two significant digits ("$0.000064"), not "$0.000": a cheap ask costs a few
// hundredths of a cent, and the chart's axis ticks must stay apart.
export const usd = (v: number) =>
  v === 0
    ? '$0'
    : v < 0.001
      ? `$${v.toFixed(Math.min(8, 1 - Math.floor(Math.log10(v))))}`
      : v < 1
        ? `$${v.toFixed(v < 0.1 ? 3 : 2)}`
        : `$${v.toFixed(2)}`;

export function metricText(v: number, metric: Metric): string {
  if (metric === 'cost') return usd(v);
  if (metric === 'time') return v < 60 ? `${Math.round(v)} s` : v < 3600 ? `${Math.round(v / 60)} min` : `${(v / 3600).toFixed(1)} h`;
  return short(v);
}

export const COLORS = ['#7F77DD', '#1D9E75', '#D85A30', '#D4537E', '#378ADD', '#BA7517'];
export const OTHER_COLOR = '#888780';
export const colorOf = (keys: string[], key: string) => (key === OTHER ? OTHER_COLOR : COLORS[keys.indexOf(key) % COLORS.length]);
