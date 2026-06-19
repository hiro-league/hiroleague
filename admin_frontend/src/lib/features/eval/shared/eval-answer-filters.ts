/** URL-synced answer-table filter query params (namespaced under `ans_*`). */
export const EVAL_ANSWER_FILTER_KEYS = [
  'ans_q',
  'ans_rec',
  'ans_cat',
  'ans_diff',
  'ans_flag',
  'ans_mark'
] as const;

export type EvalAnswerFilterKey = (typeof EVAL_ANSWER_FILTER_KEYS)[number];

/** Map a stored filter value to the pane's category/flag/mark sentinel (`all` when unset). */
export function evalAnswerFilterOrAll(value: string): string {
  return value.trim() || 'all';
}

/** True when any answer-table filter is active (excluding defaults). */
export function evalAnswerFiltersActive(filters: Record<EvalAnswerFilterKey, string>): boolean {
  return (
    filters.ans_q.trim() !== '' ||
    filters.ans_rec === '1' ||
    filters.ans_cat.trim() !== '' ||
    filters.ans_diff.trim() !== '' ||
    filters.ans_flag.trim() !== '' ||
    filters.ans_mark.trim() !== ''
  );
}
