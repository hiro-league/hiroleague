/**
 * Pure ranking / sorting / filtering / aggregation for the eval answers table + report tables.
 *
 * These were inline closures in EvalPanel.svelte that read component `$state` directly; here they
 * take their inputs as explicit parameters so they are side-effect-free and unit-testable. The
 * panel keeps the reactive `$state` (sort key/dir, filters) and passes it in at each call site.
 */
import type { EvalRow } from '$lib/features/eval/state/eval-model.svelte';
import type { EvalCategoryStat } from '$lib/features/eval/shared/eval-events';
import { markLabel } from '$lib/features/eval/shared/eval-display';
import { timeMs } from '$lib/features/eval/shared/eval-format';

/** Sortable column for the Answer Details table; `none` keeps natural question-index order. */
export type AnsSortKey = 'none' | 'recall' | 'time' | 'difficulty' | 'evidence' | 'mark';
/** Recall-sufficiency flag filter (memory track). */
export type AnsFlag = 'all' | 'sufficient' | 'miss' | 'unknown';
/** Answer-type (judge verdict) filter. */
export type AnsMark = 'all' | 'pass' | 'partial' | 'fail' | 'abstain' | 'not_judged';

// Difficulty ramp + saved-state order used as sort keys (lower sorts first ascending).
const DIFF_SORT: Record<string, number> = { medium: 0, hard: 1, very_hard: 2 };
const STATE_SORT: Record<string, number> = { '✓': 0, '◐': 1, '✗': 2, '🛇': 3, '': 4 };

// Judge-mark glyph → answer-type filter key ('' / unknown glyph ⇒ not judged).
const MARK_FILTER_KEY: Record<string, AnsMark> = {
  '✓': 'pass',
  '◐': 'partial',
  '✗': 'fail',
  '🛇': 'abstain'
};

/** Recall rank for a row's recall leg: miss (0), sufficient (1), unknown/not-judged (2). */
export function rowRecallRank(r: EvalRow): number {
  const leg = r.legs?.recall;
  if (!leg?.mark) return 2;
  return leg.recall_sufficient === false ? 0 : 1;
}

/** Difficulty rank (medium < hard < very_hard < unknown), unknown/unspecified last in ascending. */
export function rowDiffRank(r: EvalRow): number {
  return DIFF_SORT[r.difficulty || ''] ?? 3;
}

/** Evidence-recall sort key: matched/total fraction (lower = worse); rows with no gold evidence
 *  (total 0 / non-LoCoMo) get 2 so they sort LAST in ascending — same "n/a last" convention. */
export function rowEvidenceRank(r: EvalRow): number {
  const ev = r.evidence_recall;
  if (!ev || ev.total <= 0) return 2;
  return ev.matched / ev.total;
}

/** Answer-type (judge mark) rank for the recall leg (✓ < ◐ < ✗ < 🛇 < not-judged). */
export function rowMarkRank(r: EvalRow): number {
  return STATE_SORT[r.legs?.recall?.mark ?? ''] ?? 4;
}

/** Apply the active sort to a group's rows (stable on index); identity when sort is off. */
export function sortGroupRows(
  rows: EvalRow[],
  sortKey: AnsSortKey,
  sortDir: 'asc' | 'desc'
): EvalRow[] {
  if (sortKey === 'none') return rows;
  const sign = sortDir === 'asc' ? 1 : -1;
  const keyFn =
    sortKey === 'recall'
      ? rowRecallRank
      : sortKey === 'time'
        ? (r: EvalRow) => timeMs(r.answered_at)
        : sortKey === 'difficulty'
          ? rowDiffRank
          : sortKey === 'evidence'
            ? rowEvidenceRank
            : rowMarkRank; // 'mark'
  return [...rows].sort((a, b) => sign * (keyFn(a) - keyFn(b)) || a.index - b.index);
}

/** Answer-type match: ANY leg with the selected verdict counts (memory has one recall leg;
 *  knowledge legs are an at-a-glance OR — per-leg filtering isn't worth the extra controls). */
export function rowMatchesMark(r: EvalRow, ansMark: AnsMark): boolean {
  if (ansMark === 'all') return true;
  return Object.values(r.legs).some(
    (leg) => (MARK_FILTER_KEY[leg.mark] ?? 'not_judged') === ansMark
  );
}

/** Recall-sufficiency flag match (memory only) — reuses rowRecallRank's miss/ok/unknown buckets. */
export function rowMatchesFlag(r: EvalRow, ansFlag: AnsFlag): boolean {
  if (ansFlag === 'all') return true;
  const rank = rowRecallRank(r);
  return ansFlag === 'miss' ? rank === 0 : ansFlag === 'sufficient' ? rank === 1 : rank === 2;
}

/** Searchable text on a row: question/ideal/ids + per-leg answer, verdict word, judge reason +
 *  quoted evidence. The folded memory detail (recalled facts/entities/episodes AND the evidence-
 *  recall table) is included ONLY when ``includeRecalled`` is set — that detail is large/noisy. */
export function rowHaystack(r: EvalRow, includeRecalled: boolean): string {
  const parts: string[] = [r.id, r.category, r.subcategory, r.difficulty, r.question, r.gold];
  for (const leg of Object.values(r.legs)) {
    parts.push(leg.answer, markLabel(leg.mark), leg.reason ?? '', leg.evidence ?? '');
    if (includeRecalled) {
      // Recalled facts / entities / episodes (the episodes table renders ``memory``/``valid_at``).
      for (const f of leg.recalled ?? []) {
        parts.push(
          f.memory,
          f.fact ?? '',
          f.name ?? '',
          f.summary ?? '',
          f.entity_type ?? '',
          f.valid_at ?? '',
          f.invalid_at ?? ''
        );
      }
    }
  }
  // Evidence-recall table (per-row, LoCoMo) — the gold evidence episodes.
  if (includeRecalled) {
    for (const it of r.evidence_recall?.items ?? []) {
      parts.push(
        it.episode_id,
        it.short_id ?? '',
        it.dia_id ?? '',
        it.speaker ?? '',
        it.text ?? '',
        it.when ?? '',
        it.matched_via ?? ''
      );
    }
  }
  return parts.join(' ').toLowerCase();
}

/** Sum all per-bucket rows of a breakdown into one totals row (the table's "Total" line). */
export function breakdownTotals(
  bc: Record<string, EvalCategoryStat>,
  cols: string[]
): EvalCategoryStat {
  const t: EvalCategoryStat = {
    total: 0,
    groups: Object.fromEntries(cols.map((m) => [m, { pass: 0, partial: 0, fail: 0, abstain: 0 }])),
    correct: Object.fromEntries(cols.map((m) => [m, 0])),
    score: Object.fromEntries(cols.map((m) => [m, 0])),
    recall_ok: Object.fromEntries(cols.map((m) => [m, 0])),
    evidence_matched: 0,
    evidence_total: 0
  };
  for (const st of Object.values(bc)) {
    t.total += st.total;
    // Evidence recall is a single (non-leg) concept — sum the bucket scalars directly.
    t.evidence_matched = (t.evidence_matched ?? 0) + (st.evidence_matched ?? 0);
    t.evidence_total = (t.evidence_total ?? 0) + (st.evidence_total ?? 0);
    for (const m of cols) {
      const g = st.groups?.[m];
      if (g) {
        t.groups[m].pass += g.pass;
        t.groups[m].partial += g.partial;
        t.groups[m].fail += g.fail;
        t.groups[m].abstain += g.abstain;
      }
      t.correct[m] += st.correct?.[m] ?? 0;
      t.score[m] += st.score?.[m] ?? 0;
      t.recall_ok[m] += st.recall_ok?.[m] ?? 0;
    }
  }
  return t;
}
