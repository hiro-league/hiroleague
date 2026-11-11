/**
 * A timestamp as a tight two-line table cell (`{ date, time }` plus a full `title` for hover), from an
 * epoch or ISO value. Shared by the Graph Runs ledger list and the Memories table. The words come from
 * the one formatter, `$lib/format/time` (UI kit step 1d).
 */
import { clock, fullDateTime, shortDate } from './time';

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

/** Stacked date + time strings (plus the full date for `title`); `—` when unparseable. */
export function formatCompactDateTime(value: unknown): { date: string; time: string; title: string } {
  const d = parseFlexibleDate(value);
  if (!d) return { date: '—', time: '—', title: '' };
  return { date: shortDate(d), time: clock(d, true), title: fullDateTime(d) };
}
