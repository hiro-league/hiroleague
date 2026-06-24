/**
 * Pure helpers that let the eval detail dialog REPLICATE what the answerer actually saw for a
 * recall leg: which recalled items were sent (top-K per kind by score — the rest were capped out
 * and are struck through) and how each item's text was trimmed (one sanitized capped line). Kept
 * side-effect free (no Svelte runtime) so the dialog and any future consumer share one source of
 * truth, in lockstep with the backend (`services/eval/judge.py`).
 */
import type { EvalRecallRender, RecalledFact } from '$lib/features/eval/shared/eval-events';
import { rowMatches } from '$lib/search/match';

/** Caps for legs/runs predating the stamped `render` field (mirror the graph.eval pref defaults). */
export const DEFAULT_RECALL_RENDER: EvalRecallRender = {
  max_elements_per_kind: 30,
  max_fact_chars: 240,
  max_episode_chars: 300,
  max_summary_chars: 400
};

// Hardcoded entity-name cap in judge._format_recall_item (not a pref) — mirrored here so the
// trimmed entity name matches the prompt.
const ENTITY_NAME_CAP = 120;

/** Port of judge._sanitize_oneline: collapse whitespace, strip leading markdown markers
 *  (#, >, *, `, -), then truncate to `cap` chars with an ellipsis. MUST stay character-for-character
 *  with the backend so the "trimmed" view equals the line the answerer read. */
export function sanitizeOneline(text: string | null | undefined, cap: number): string {
  let s = String(text ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  s = s.replace(/^[#>*`\-\s]+/, '');
  if (cap > 0 && s.length > cap) s = s.slice(0, cap - 1).replace(/\s+$/, '') + '…';
  return s;
}

/** Retrieval score for ranking (desc); missing/garbage → 0.0 so it sorts last — matches judge._score_of. */
export function scoreOf(row: RecalledFact): number {
  return typeof row.score === 'number' && Number.isFinite(row.score) ? row.score : 0;
}

/** The rows that actually reached the answerer: top `cap` by score (desc, stable on the stored
 *  order), exactly as judge.format_recall_context keeps per kind. Everything else was capped out. */
export function sentSet(rows: RecalledFact[], cap: number): Set<RecalledFact> {
  if (cap <= 0 || rows.length <= cap) return new Set(rows);
  const ranked = rows
    .map((r, i) => ({ r, i, s: scoreOf(r) }))
    .sort((a, b) => b.s - a.s || a.i - b.i);
  return new Set(ranked.slice(0, cap).map((x) => x.r));
}

/** Number of items of a kind that were sent to eval (min of the cap and the total). */
export function sentCount(total: number, cap: number): number {
  return cap > 0 ? Math.min(cap, total) : total;
}

/** Per-kind char cap for the item's main text field (fact / episode body / entity summary). */
export function textCapFor(kind: RecalledFact['kind'], render: EvalRecallRender): number {
  if (kind === 'entity') return render.max_summary_chars;
  if (kind === 'episode') return render.max_episode_chars;
  return render.max_fact_chars;
}

/** An item's main display text, trimmed to the eval cap when `trimmed`, raw otherwise. */
export function itemText(
  raw: string | null | undefined,
  cap: number,
  trimmed: boolean
): string {
  return trimmed ? sanitizeOneline(raw, cap) : String(raw ?? '');
}

/** Trimmed entity name (matches the hardcoded 120-char cap), or the raw name when not trimming. */
export function entityName(raw: string | null | undefined, trimmed: boolean): string {
  return trimmed ? sanitizeOneline(raw, ENTITY_NAME_CAP) : String(raw ?? '');
}

/** The text a recalled row is searched/filtered against (all the human-readable fields). */
export function recalledSearchText(row: RecalledFact): string {
  return [row.memory, row.fact, row.name, row.summary, row.entity_type]
    .filter(Boolean)
    .join(' ');
}

/** Case-insensitive substring match of a recalled row against the search term ('' ⇒ matches all). */
export function recalledMatches(row: RecalledFact, term: string): boolean {
  if (!term.trim()) return true;
  return rowMatches(row, term, (r) => [recalledSearchText(r)]);
}

/** Tab badge text: "sent/total" normally, "shown/total" while searching (shown = rows that match). */
export function recalledTabCount(rows: RecalledFact[], cap: number, term: string): string {
  const total = rows.length;
  if (term.trim()) return `${rows.filter((r) => recalledMatches(r, term)).length}/${total}`;
  return `${sentCount(total, cap)}/${total}`;
}

// --- Column sorting (shared by the recalled tables + the evidence table) --------------------------

export type SortDir = 1 | -1;
export type SortState = { key: string; dir: SortDir };

/** Click-to-sort cycle for a header: new column → asc, asc → desc, desc → back to the default. */
export function nextSort(cur: SortState, key: string, fallback: SortState): SortState {
  if (cur.key !== key) return { key, dir: 1 };
  if (cur.dir === 1) return { key, dir: -1 };
  return fallback;
}

/** Stable sort by `state.key` via `accessor`; numbers compare numerically, everything else as text.
 *  Ties keep the original (stored) order regardless of direction. */
export function sortRows<T>(
  rows: T[],
  state: SortState,
  accessor: (row: T, key: string) => string | number
): T[] {
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const va = accessor(a.r, state.key);
      const vb = accessor(b.r, state.key);
      let c: number;
      if (typeof va === 'number' && typeof vb === 'number') c = va - vb;
      else c = String(va).localeCompare(String(vb));
      return c !== 0 ? c * state.dir : a.i - b.i;
    })
    .map((x) => x.r);
}

/** ▲ / ▼ / '' for a header cell given the active sort. */
export function sortArrow(state: SortState, key: string): string {
  if (state.key !== key) return '';
  return state.dir === 1 ? '▲' : '▼';
}

/** aria-sort value for a header cell given the active sort. */
export function ariaSort(state: SortState, key: string): 'ascending' | 'descending' | 'none' {
  if (state.key !== key) return 'none';
  return state.dir === 1 ? 'ascending' : 'descending';
}
