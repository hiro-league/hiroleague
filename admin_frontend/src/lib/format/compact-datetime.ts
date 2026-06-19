/**
 * Feature-neutral compact date/time formatting for dense admin tables.
 *
 * Produces a two-line `{ date, time }` cell plus a full `title` for hover. Shared
 * by the Graph Runs ledger list and the Memories table (both render an epoch or
 * ISO timestamp as a tight stacked cell).
 */

const compactDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const compactTime12h = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true
});

/**
 * Parse a flexible timestamp into a `Date` (or `null`). Accepts epoch numbers
 * (seconds or milliseconds — values past the year ~2286 cutoff are treated as ms),
 * numeric strings, and ISO date strings.
 */
export function parseFlexibleDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 10_000_000_000 ? value : value * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  if (Number.isFinite(numeric)) return parseFlexibleDate(numeric);
  const d = new Date(trimmed);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Stacked date + time strings (plus a full locale string for `title`); `—` when unparseable. */
export function formatCompactDateTime(value: unknown): { date: string; time: string; title: string } {
  const d = parseFlexibleDate(value);
  if (!d) return { date: '—', time: '—', title: '' };
  return {
    date: compactDate.format(d),
    time: compactTime12h.format(d),
    title: d.toLocaleString()
  };
}
