export type TableFiltersController<TKey extends string> = {
  readonly filters: Record<TKey, string>;
  set: (key: TKey, value: string) => void;
  reset: () => void;
};

function emptyFilters<TKey extends string>(
  keys: readonly TKey[],
  defaults: Partial<Record<TKey, string>> = {}
): Record<TKey, string> {
  return keys.reduce(
    (acc, key) => {
      acc[key] = defaults[key] ?? '';
      return acc;
    },
    {} as Record<TKey, string>
  );
}

function readFiltersFromUrl<TKey extends string>(
  keys: readonly TKey[],
  defaults: Partial<Record<TKey, string>>,
  params: URLSearchParams
): Record<TKey, string> {
  const out = emptyFilters(keys, defaults);
  for (const key of keys) {
    const value = params.get(key);
    if (value !== null) {
      out[key] = value;
    }
  }
  return out;
}

function writeFiltersToUrl<TKey extends string>(keys: readonly TKey[], filters: Record<TKey, string>) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  for (const key of keys) {
    const value = filters[key]?.trim() ?? '';
    if (value) {
      url.searchParams.set(key, value);
    } else {
      url.searchParams.delete(key);
    }
  }
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

export function useTableFilters<TKey extends string>(opts: {
  keys: readonly TKey[];
  defaults?: Partial<Record<TKey, string>>;
  urlSync?: boolean;
}): TableFiltersController<TKey> {
  const defaults = opts.defaults ?? {};
  const initial =
    opts.urlSync && typeof window !== 'undefined'
      ? readFiltersFromUrl(opts.keys, defaults, new URL(window.location.href).searchParams)
      : emptyFilters(opts.keys, defaults);

  let filters = $state<Record<TKey, string>>(initial);

  // Re-read the query string on browser history navigation (back/forward) so the
  // in-memory filters track the address bar. We only replaceState on write, so
  // without this popstate would desync the URL from the visible table. Auto-removed
  // on teardown.
  if (opts.urlSync && typeof window !== 'undefined') {
    $effect(() => {
      function rereadFromUrl() {
        filters = readFiltersFromUrl(opts.keys, defaults, new URL(window.location.href).searchParams);
      }
      window.addEventListener('popstate', rereadFromUrl);
      return () => window.removeEventListener('popstate', rereadFromUrl);
    });
  }

  function set(key: TKey, value: string) {
    // Keep in-memory filters aligned with the trimmed values written to the URL.
    const stored = opts.urlSync ? value.trim() : value;
    filters = { ...filters, [key]: stored };
    if (opts.urlSync) {
      writeFiltersToUrl(opts.keys, filters);
    }
  }

  function reset() {
    filters = emptyFilters(opts.keys, defaults);
    if (opts.urlSync) {
      writeFiltersToUrl(opts.keys, filters);
    }
  }

  return {
    get filters() {
      return filters;
    },
    set,
    reset
  };
}
