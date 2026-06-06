/** Shared table cell / control classes for Graph Runs ledger tables. */
export const graphRunsTableLinkClass =
  'border-0 bg-transparent p-0 font-inherit text-primary underline-offset-2 hover:underline';

/** Matches former `.preview` cells in GraphRunsRunsPanel. */
export const graphRunsPreviewCellClass =
  'max-w-[220px] overflow-hidden text-ellipsis';

/** Matches former `.runs-list-name-cell`. */
export const graphRunsNameCellClass =
  'max-w-40 overflow-hidden text-ellipsis';

/** Compact date + time stack (Graph runs list, Memories date columns). */
export const graphRunsDateCellClass =
  'min-w-[86px] whitespace-nowrap font-sans text-muted-foreground [&>span]:block [&>span]:leading-[1.35]';

/** Inner wrapper — flex must not be applied to `<td>` (breaks table row height). */
export const graphRunsRunCellInnerClass = 'flex min-w-0 items-center gap-1.5 whitespace-nowrap';

export const graphRunsLogsIconLinkClass =
  'inline-flex shrink-0 text-primary transition-colors hover:text-primary/80';

/** Memories table allows wrapped text (former `.memories-table-wrap`). */
export const graphRunsMemoriesTableShellClass = 'memories-table-wrap';
