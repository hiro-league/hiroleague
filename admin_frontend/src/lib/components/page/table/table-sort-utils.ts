export type TableSortDirection = 'asc' | 'desc';

export type AriaSortValue = 'ascending' | 'descending' | 'none';

/** Cycle sort when a column header is clicked: new column → asc; same column toggles asc/desc. */
export function cycleTableSort<TCol extends string>(
  activeColumn: TCol,
  activeDirection: TableSortDirection,
  column: TCol
): { sortBy: TCol; direction: TableSortDirection } {
  if (activeColumn !== column) {
    return { sortBy: column, direction: 'asc' };
  }
  return {
    sortBy: column,
    direction: activeDirection === 'asc' ? 'desc' : 'asc'
  };
}

export function tableSortAria(
  activeColumn: string,
  activeDirection: TableSortDirection,
  column: string
): AriaSortValue {
  if (activeColumn !== column) return 'none';
  return activeDirection === 'asc' ? 'ascending' : 'descending';
}
