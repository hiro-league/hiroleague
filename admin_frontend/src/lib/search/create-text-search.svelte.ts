import { untrack } from 'svelte';
import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';

export type TextSearchController = {
  readonly query: string;
  readonly debounced: string;
  set(q: string): void;
  /** Clears the query and runs `onCommit('')`. */
  clear(): void;
  /** Sets query/debounced without scheduling or calling `onCommit` (bulk filter reset). */
  sync(q: string): void;
  teardown(): void;
};

export function createTextSearch(opts?: {
  debounceMs?: number;
  urlKey?: string;
  onCommit?: (q: string) => void;
}): TextSearchController {
  const debounceMs = opts?.debounceMs ?? 0;
  const urlKey = opts?.urlKey;

  const urlFilters = urlKey
    ? useTableFilters({ keys: [urlKey] as [string], urlSync: true })
    : null;

  const initialQuery = urlFilters && urlKey ? urlFilters.filters[urlKey] : '';
  let query = $state(initialQuery);
  let debounced = $state(initialQuery);
  let timer: ReturnType<typeof setTimeout> | null = null;

  if (urlFilters && urlKey) {
    $effect(() => {
      // React ONLY to external URL changes (back/forward → useTableFilters' popstate
      // re-read). Reading `query` reactively here would re-fire the effect on every
      // keystroke and, with debounceMs > 0, revert the in-flight input to the stale URL
      // value before the debounce commits. untrack() keeps the local-typing reads/writes
      // out of the effect's dependency set.
      const fromUrl = urlFilters.filters[urlKey];
      untrack(() => {
        if (fromUrl === query) return;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        query = fromUrl;
        debounced = fromUrl;
      });
    });
  }

  function writeUrl(q: string) {
    if (urlFilters && urlKey) {
      urlFilters.set(urlKey, q);
    }
  }

  function commitNow(q: string) {
    debounced = q;
    writeUrl(q);
    opts?.onCommit?.(q);
  }

  function scheduleCommit() {
    if (timer) clearTimeout(timer);
    if (debounceMs === 0) {
      commitNow(query);
      return;
    }
    timer = setTimeout(() => {
      timer = null;
      commitNow(query);
    }, debounceMs);
  }

  function set(q: string) {
    query = q;
    scheduleCommit();
  }

  function sync(q: string) {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    query = q;
    debounced = q;
    writeUrl(q);
  }

  function clear() {
    sync('');
    opts?.onCommit?.('');
  }

  function teardown() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  return {
    get query() {
      return query;
    },
    get debounced() {
      return debounced;
    },
    set,
    clear,
    sync,
    teardown
  };
}
