export type TableSortDirection = 'asc' | 'desc';
export type TableSortDirectionWithNone = TableSortDirection | 'none';

export type AriaSortValue = 'ascending' | 'descending' | 'none';

/** Cycle sort when a column header is clicked: new column → asc; same column toggles asc/desc (or asc→desc→none when threeState). */
export function cycleTableSort<TCol extends string>(
  activeColumn: TCol,
  activeDirection: TableSortDirectionWithNone,
  column: TCol,
  opts?: { threeState?: boolean }
): { sortBy: TCol; direction: TableSortDirectionWithNone } {
  if (activeColumn !== column) {
    return { sortBy: column, direction: 'asc' };
  }
  if (!opts?.threeState) {
    return {
      sortBy: column,
      direction: activeDirection === 'asc' ? 'desc' : 'asc'
    };
  }
  if (activeDirection === 'asc') {
    return { sortBy: column, direction: 'desc' };
  }
  if (activeDirection === 'desc') {
    return { sortBy: column, direction: 'none' };
  }
  return { sortBy: column, direction: 'asc' };
}

export function asTableSortDirection(direction: TableSortDirectionWithNone): TableSortDirection {
  return direction === 'none' ? 'asc' : direction;
}

export function tableSortAria(
  activeColumn: string,
  activeDirection: TableSortDirectionWithNone,
  column: string
): AriaSortValue {
  if (activeColumn !== column || activeDirection === 'none') return 'none';
  return activeDirection === 'asc' ? 'ascending' : 'descending';
}
