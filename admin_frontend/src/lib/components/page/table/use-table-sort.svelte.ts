import { cycleTableSort, tableSortAria, type TableSortDirection } from './table-sort-utils';

export type { TableSortDirection, AriaSortValue } from './table-sort-utils';

export type TableSortController<TCol extends string> = {
  readonly sortBy: TCol;
  readonly direction: TableSortDirection;
  toggle: (column: TCol) => void;
  ariaSort: (column: TCol) => ReturnType<typeof tableSortAria>;
  setSort: (column: TCol, direction: TableSortDirection) => void;
};

type UrlSyncOpts = {
  sortParam?: string;
  directionParam?: string;
};

function readSortFromUrl<TCol extends string>(
  allowed: readonly TCol[],
  defaultBy: TCol,
  defaultDirection: TableSortDirection,
  params: URLSearchParams,
  keys: UrlSyncOpts
): { sortBy: TCol; direction: TableSortDirection } {
  const sortParam = keys.sortParam ?? 'sort';
  const directionParam = keys.directionParam ?? 'sort_dir';
  const rawSort = params.get(sortParam);
  const rawDir = params.get(directionParam);
  const sortBy =
    rawSort && (allowed as readonly string[]).includes(rawSort) ? (rawSort as TCol) : defaultBy;
  const direction: TableSortDirection = rawDir === 'desc' ? 'desc' : defaultDirection;
  return { sortBy, direction };
}

function writeSortToUrl(
  sortBy: string,
  direction: TableSortDirection,
  keys: UrlSyncOpts
) {
  if (typeof window === 'undefined') return;
  const sortParam = keys.sortParam ?? 'sort';
  const directionParam = keys.directionParam ?? 'sort_dir';
  const url = new URL(window.location.href);
  url.searchParams.set(sortParam, sortBy);
  url.searchParams.set(directionParam, direction);
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

export function useTableSort<TCol extends string>(opts: {
  defaultBy: TCol;
  defaultDirection?: TableSortDirection;
  allowed: readonly TCol[];
  urlSync?: boolean;
  sortParam?: string;
  directionParam?: string;
}): TableSortController<TCol> {
  const defaultDirection = opts.defaultDirection ?? 'asc';
  const urlKeys: UrlSyncOpts = {
    sortParam: opts.sortParam,
    directionParam: opts.directionParam
  };

  const initial =
    opts.urlSync && typeof window !== 'undefined'
      ? readSortFromUrl(
          opts.allowed,
          opts.defaultBy,
          defaultDirection,
          new URL(window.location.href).searchParams,
          urlKeys
        )
      : { sortBy: opts.defaultBy, direction: defaultDirection };

  let sortBy = $state<TCol>(initial.sortBy);
  let direction = $state<TableSortDirection>(initial.direction);

  function setSort(column: TCol, nextDirection: TableSortDirection) {
    sortBy = column;
    direction = nextDirection;
    if (opts.urlSync) {
      writeSortToUrl(column, nextDirection, urlKeys);
    }
  }

  function toggle(column: TCol) {
    const next = cycleTableSort(sortBy, direction, column);
    setSort(next.sortBy, next.direction);
  }

  return {
    get sortBy() {
      return sortBy;
    },
    get direction() {
      return direction;
    },
    toggle,
    ariaSort(column: TCol) {
      return tableSortAria(sortBy, direction, column);
    },
    setSort
  };
}
