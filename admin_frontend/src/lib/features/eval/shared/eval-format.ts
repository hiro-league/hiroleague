/**
 * Shared number / size formatting for the eval corpus UI.
 *
 * `approxTokens` is a cheap heuristic (≈ chars / 4) used only for the "text size"
 * readouts in the corpus picker/header — it is NOT an exact tokenizer count.
 */

const INT = new Intl.NumberFormat('en-US');

/** Round to one decimal, dropping a trailing ".0" (12.34 → "12.3", 120.0 → "120"). */
function trim1(x: number): string {
  return String(Math.round(x * 10) / 10);
}

/** Full integer with thousands separators (e.g. 48231 → "48,231"). */
export function fmtCount(n: number): string {
  return INT.format(Math.max(0, Math.round(n)));
}

/** Compact K/M form for large counts (1234 → "1.2K", 1_250_000 → "1.3M"); commas under 1000. */
export function fmtCompact(n: number): string {
  const v = Math.max(0, Math.round(n));
  if (v < 1_000) return INT.format(v);
  if (v < 1_000_000) return `${trim1(v / 1_000)}K`;
  return `${trim1(v / 1_000_000)}M`;
}

/** Approximate token count for a body of text (≈ 4 chars/token). Heuristic, not exact. */
export function approxTokens(text: string | null | undefined): number {
  return Math.round((text?.length ?? 0) / 4);
}

/** Cost (LLM + reranker; embeddings unpriced). Sub-cent shows 4dp, else 2dp; non-positive → "$0.00". */
export function fmtCost(v: number | null | undefined): string {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n) || n <= 0) return '$0.00';
  return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

/** Score can be fractional (partial = ½ pt); show one decimal only when needed (e.g. 12.5, 13). */
export function fmtScore(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Whole-number percentage for the report tables (n/total ⇒ "0%"–"100%"); "—" when total is 0. */
export function pct(n: number, total: number): string {
  if (!total || total <= 0) return '—';
  return `${Math.round((n / total) * 100)}%`;
}

// Eval-time helpers for the "Time" column: clock-only display, full date in the tooltip, and an
// epoch-ms key for sorting (so we display the time but order by the actual date).
export function fmtTime(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
export function fmtDateTime(iso: string | undefined): string {
  if (!iso) return 'Not run yet';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
export function timeMs(iso: string | undefined): number {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? 0 : t;
}

// Episode timestamps are dated turns (fictional far-future dates); show the date only — the
// time-of-day is noise for a review-at-a-glance. ISO slice keeps the UTC date stable.
export function fmtEpisodeDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}
