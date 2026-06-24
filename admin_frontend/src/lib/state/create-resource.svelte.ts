import type { Notify } from '$lib/ui/toast-types';
import { featureErrorFrom } from '$lib/runtime/feature-errors';
import type { Resource } from './types';

function formatLoadError(err: unknown, errorPrefix?: string): string | null {
  return featureErrorFrom(err, errorPrefix ?? 'Request failed.');
}

export function createResource<T>(
  loader: () => Promise<T>,
  opts: { initial: T; errorPrefix?: string; initialLoading?: boolean }
): Resource<T> {
  let data = $state<T>(opts.initial);
  let loading = $state(opts.initialLoading ?? false);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  async function load(o?: { silent?: boolean }): Promise<T> {
    if (!o?.silent) loading = true;
    error = null;
    let next = data;
    try {
      next = await loader();
      data = next;
    } catch (err) {
      const message = formatLoadError(err, opts.errorPrefix);
      error = message;
    } finally {
      loading = false;
      loaded = true;
    }
    return next;
  }

  function replace(value: T) {
    data = value;
    error = null;
  }

  function reset() {
    data = opts.initial;
    error = null;
    loaded = false;
  }

  return {
    get data() {
      return data;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    get loaded() {
      return loaded;
    },
    load,
    replace,
    reset
  };
}

export type ListSelection<Row, Id> = {
  selectedId: Id | null;
  readonly selected: Row | null;
  select(id: Id | null): void;
  /** Point selection resolution at the current candidate rows (e.g. filtered visible rows). */
  setCandidates(rows: Row[]): void;
  reconcile(): void;
  /** Alias for `reconcile()` — kept for list resources that sync selection after reload. */
  reconcileSelection(): void;
};

/** Row selection without an attached loader — for lists owned elsewhere (e.g. logs visible rows). */
export function createListSelection<Row, Id = string>(opts: {
  getId: (row: Row) => Id;
}): ListSelection<Row, Id> {
  let selectedId = $state<Id | null>(null);
  let candidates = $state<Row[]>([]);

  const selected = $derived(
    selectedId == null
      ? null
      : (candidates.find((row) => opts.getId(row) === selectedId) ?? null)
  );

  function select(id: Id | null) {
    selectedId = id;
  }

  function setCandidates(rows: Row[]) {
    candidates = rows;
  }

  function reconcile() {
    if (selectedId == null) return;
    if (!candidates.some((row) => opts.getId(row) === selectedId)) {
      selectedId = null;
    }
  }

  return {
    get selectedId() {
      return selectedId;
    },
    set selectedId(id: Id | null) {
      selectedId = id;
    },
    get selected() {
      return selected;
    },
    select,
    setCandidates,
    reconcile,
    reconcileSelection() {
      reconcile();
    }
  };
}

export type ListResource<Row, Id> = Resource<Row[]> & ListSelection<Row, Id>;

export function createListResource<Row, Id = string>(
  loader: () => Promise<Row[]>,
  opts: { getId: (row: Row) => Id; errorPrefix?: string; initialLoading?: boolean }
): ListResource<Row, Id> {
  const resource = createResource(loader, {
    initial: [] as Row[],
    errorPrefix: opts.errorPrefix,
    initialLoading: opts.initialLoading
  });
  const selection = createListSelection<Row, Id>({ getId: opts.getId });

  async function load(o?: { silent?: boolean }) {
    const rows = await resource.load(o);
    selection.setCandidates(rows);
    selection.reconcile();
    return rows;
  }

  return {
    get data() {
      return resource.data;
    },
    get loading() {
      return resource.loading;
    },
    get error() {
      return resource.error;
    },
    get loaded() {
      return resource.loaded;
    },
    get selectedId() {
      return selection.selectedId;
    },
    set selectedId(id: Id | null) {
      selection.selectedId = id;
    },
    get selected() {
      return selection.selected;
    },
    load,
    replace(value: Row[]) {
      resource.replace(value);
      selection.setCandidates(value);
      selection.reconcile();
    },
    reset() {
      resource.reset();
      selection.select(null);
      selection.setCandidates([]);
    },
    select: selection.select,
    setCandidates(rows: Row[]) {
      selection.setCandidates(rows);
    },
    reconcile() {
      selection.reconcile();
    },
    reconcileSelection() {
      selection.reconcile();
    }
  };
}

export type Mutation<A extends unknown[] = [], R = unknown> = {
  readonly busy: boolean;
  run(...args: A): Promise<void>;
};

export function createMutation<A extends unknown[] = [], R = unknown>(
  fn: (...args: A) => Promise<R>,
  opts: {
    notify: Notify;
    successMsg?: string | ((result: R) => string | undefined);
    errorPrefix?: string;
    onDone?: (result: R) => void | Promise<void>;
  }
): Mutation<A, R> {
  let busy = $state(false);

  async function run(...args: A) {
    busy = true;
    try {
      const result = await fn(...args);
      const msg =
        typeof opts.successMsg === 'function' ? opts.successMsg(result) : opts.successMsg;
      if (msg) opts.notify('success', msg);
      await opts.onDone?.(result);
    } catch (err) {
      const message = formatLoadError(err, opts.errorPrefix);
      if (message) opts.notify('error', message);
    } finally {
      busy = false;
    }
  }

  return {
    get busy() {
      return busy;
    },
    run
  };
}
