export type DistinctOption = { value: string; label: string };

const DEFAULT_EMPTY_VALUE = '__empty__';
const DEFAULT_EMPTY_LABEL = '(no value)';

/**
 * Build sorted `{ value, label }` options from row values. When any row yields a blank value,
 * a sentinel option is prepended (defaults: `__empty__` / `(no value)`).
 */
export function distinctOptionsWithSentinel<T>(
  rows: readonly T[],
  accessor: (row: T) => string | undefined,
  opts?: {
    emptyLabel?: string;
    emptyValue?: string;
    /** When false, preserve first-seen order instead of locale sorting. Default true. */
    sort?: boolean;
  }
): DistinctOption[] {
  const emptyValue = opts?.emptyValue ?? DEFAULT_EMPTY_VALUE;
  const emptyLabel = opts?.emptyLabel ?? DEFAULT_EMPTY_LABEL;
  const sort = opts?.sort ?? true;

  const raw = new Set<string>();
  let anyEmpty = false;
  const firstSeen: string[] = [];

  for (const row of rows) {
    const s = String(accessor(row) ?? '').trim();
    if (s === '') {
      anyEmpty = true;
      continue;
    }
    if (!raw.has(s)) {
      raw.add(s);
      firstSeen.push(s);
    }
  }

  const out: DistinctOption[] = [];
  if (anyEmpty) out.push({ value: emptyValue, label: emptyLabel });

  const values = sort ? [...raw].sort((a, b) => a.localeCompare(b)) : firstSeen;
  for (const s of values) {
    out.push({ value: s, label: s });
  }
  return out;
}

export { DEFAULT_EMPTY_VALUE as DISTINCT_EMPTY_VALUE };
