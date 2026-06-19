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
