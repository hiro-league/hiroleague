import { cycleTableSort, tableSortAria, type TableSortDirection, type TableSortDirectionWithNone } from './table-sort-utils';

export type { TableSortDirection, TableSortDirectionWithNone, AriaSortValue } from './table-sort-utils';

export type TableSortController<TCol extends string> = {
  readonly sortBy: TCol;
  readonly direction: TableSortDirectionWithNone;
  toggle: (column: TCol) => void;
  ariaSort: (column: TCol) => ReturnType<typeof tableSortAria>;
  setSort: (column: TCol, direction: TableSortDirectionWithNone) => void;
};

type UrlSyncOpts = {
  sortParam?: string;
  directionParam?: string;
};

function readSortFromUrl<TCol extends string>(
  allowed: readonly TCol[],
  defaultBy: TCol,
  defaultDirection: TableSortDirection | TableSortDirectionWithNone,
  params: URLSearchParams,
  keys: UrlSyncOpts
): { sortBy: TCol; direction: TableSortDirectionWithNone } {
  const sortParam = keys.sortParam ?? 'sort';
  const directionParam = keys.directionParam ?? 'sort_dir';
  const rawSort = params.get(sortParam);
  const rawDir = params.get(directionParam);
  const sortBy =
    rawSort && (allowed as readonly string[]).includes(rawSort) ? (rawSort as TCol) : defaultBy;
  const direction: TableSortDirectionWithNone =
    rawDir === 'desc' || rawDir === 'asc' || rawDir === 'none' ? rawDir : defaultDirection;
  return { sortBy, direction };
}

function writeSortToUrl(
  sortBy: string,
  direction: TableSortDirectionWithNone,
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
  defaultDirection?: TableSortDirection | TableSortDirectionWithNone;
  allowed: readonly TCol[];
  urlSync?: boolean;
  sortParam?: string;
  directionParam?: string;
  threeState?: boolean;
}): TableSortController<TCol> {
  const defaultDirection = opts.defaultDirection ?? 'asc';
  const threeState = opts.threeState ?? false;
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
  let direction = $state<TableSortDirectionWithNone>(initial.direction);

  // Keep in-memory sort aligned with the address bar when the user navigates
  // browser history (back/forward). Without this, popstate leaves the URL and the
  // visible ordering out of sync. Registered once; auto-removed on teardown.
  if (opts.urlSync && typeof window !== 'undefined') {
    $effect(() => {
      function rereadFromUrl() {
        const next = readSortFromUrl(
          opts.allowed,
          opts.defaultBy,
          defaultDirection,
          new URL(window.location.href).searchParams,
          urlKeys
        );
        sortBy = next.sortBy;
        direction = next.direction;
      }
      window.addEventListener('popstate', rereadFromUrl);
      return () => window.removeEventListener('popstate', rereadFromUrl);
    });
  }

  function setSort(column: TCol, nextDirection: TableSortDirectionWithNone) {
    sortBy = column;
    direction = nextDirection;
    if (opts.urlSync) {
      writeSortToUrl(column, nextDirection, urlKeys);
    }
  }

  function toggle(column: TCol) {
    const next = cycleTableSort(sortBy, direction, column, { threeState });
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
