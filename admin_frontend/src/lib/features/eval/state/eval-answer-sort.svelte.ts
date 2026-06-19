import {
  tableSortAria,
  type TableSortDirection
} from '$lib/components/page/table/table-sort-utils';
import type { AnsSortKey } from '$lib/features/eval/shared/eval-derive';

/** Sortable answer-table columns (`none` = natural index order within each group). */
export type EvalAnswerSortColumn = Exclude<AnsSortKey, 'none'>;

export type EvalAnswerSortController = {
  readonly sortKey: AnsSortKey;
  readonly sortDir: TableSortDirection;
  toggle: (column: EvalAnswerSortColumn) => void;
  ariaSort: (column: EvalAnswerSortColumn) => ReturnType<typeof tableSortAria>;
};

/** Three-state column sort: off → asc → desc → off (eval groups keep index order when off). */
export function useEvalAnswerSort(): EvalAnswerSortController {
  let sortKey = $state<AnsSortKey>('none');
  let sortDir = $state<TableSortDirection>('asc');

  function toggle(column: EvalAnswerSortColumn) {
    if (sortKey !== column) {
      sortKey = column;
      sortDir = 'asc';
    } else if (sortDir === 'asc') {
      sortDir = 'desc';
    } else {
      sortKey = 'none';
      sortDir = 'asc';
    }
  }

  return {
    get sortKey() {
      return sortKey;
    },
    get sortDir() {
      return sortDir;
    },
    toggle,
    ariaSort(column) {
      if (sortKey === 'none' || sortKey !== column) return 'none';
      return tableSortAria(sortKey, sortDir, column);
    }
  };
}
