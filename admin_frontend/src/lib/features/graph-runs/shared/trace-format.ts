/**
 * Side-effect-free formatters and predicates shared by the ingest + retrieval trace dialogs.
 * Extracted from the (formerly monolithic) `*TraceDialog.svelte` files so the parsing /
 * formatting logic stays unit-testable and the two dialogs share one implementation —
 * `isCurrent`, `temporalTitle`, the ISO date formatters and the cell formatters were byte-for-byte
 * duplicated across both before this split.
 */

/** Bi-temporal validity fields common to ingest edges and retrieval items. */
export type TemporalBounds = {
  valid_at?: string | null;
  invalid_at?: string | null;
  expired_at?: string | null;
};

/**
 * A fact is "current" iff neither the event-time end (`invalid_at`) nor the system expiry
 * (`expired_at`) is set. In graphiti 0.29.1 these are always set together (see edges.py), so
 * either one flips the fact to superseded. Drives the green/red validity pill.
 */
export function isCurrent(x: TemporalBounds): boolean {
  return !(x.invalid_at || x.expired_at);
}

/** Full bi-temporal detail (incl. the system expired_at) for the validity pill tooltip. */
export function temporalTitle(x: TemporalBounds): string {
  const lines: string[] = [];
  if (x.valid_at) lines.push(`became true: ${x.valid_at}`);
  if (x.invalid_at) lines.push(`stopped being true: ${x.invalid_at}`);
  if (x.expired_at) lines.push(`system-expired: ${x.expired_at}`);
  return lines.length ? lines.join('\n') : 'no temporal bounds';
}

// ── Human-readable dates ──────────────────────────────────────────────────────────────────
// graphiti stores microsecond ISO timestamps (`2213-11-30T08:00:00.000000Z`) and the eval
// corpus uses far-future years, so we format by regex (not `Date`, which chokes on 6-digit
// fractional seconds) into `30 Nov 2213, 08:00 UTC`. Raw ISO stays in the tooltip + Raw JSON.
export const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
];
export const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;

export function isISO(v: unknown): v is string {
  return typeof v === 'string' && ISO_RE.test(v);
}

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return '';
  const m = ISO_RE.exec(String(iso));
  if (!m) return String(iso);
  const [, y, mo, d, hh, mm] = m;
  const month = MONTHS[Number(mo) - 1] ?? mo;
  let out = `${Number(d)} ${month} ${y}`;
  if (withTime && hh !== undefined) out += `, ${hh}:${mm} UTC`;
  return out;
}

/** Date-only (YYYY-MM-DD) slice for the dense retrieval tables. */
export function shortDate(iso: string | null | undefined): string {
  return iso ? String(iso).slice(0, 10) : '';
}

// ── Cell value formatting ───────────────────────────────────────────────────────────────────
export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** A single value as a compact cell — scalars verbatim, nested structures as compact JSON. */
export function cell(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export function prettyKey(key: string): string {
  return key.replace(/_/g, ' ');
}

/** Stage score as a fixed 4-decimal string, or `—` when absent (raw bm25/cosine legs). */
export function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined ? '—' : score.toFixed(4);
}

/** Episode `source` with graphiti's `EpisodeType.` prefix stripped; `—` when empty. */
export function episodeSourceLabel(source: string | null | undefined): string {
  const src = (source ?? '').replace(/^EpisodeType\./, '');
  return src || '—';
}
