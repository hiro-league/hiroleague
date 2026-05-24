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

  function set(key: TKey, value: string) {
    filters = { ...filters, [key]: value };
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
