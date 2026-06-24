import { browser } from '$app/environment';
import type { Codec } from './codecs';

export type StorageTier = 'url' | 'session' | 'local';

// Storage access is wrapped in try/catch: localStorage/sessionStorage throw in some embedded
// contexts (Safari private mode, blocked third-party storage) and setItem throws on quota. The
// pre-refactor stores (e.g. chat-overlay-store) swallowed these; keep that resilience here so a
// failed persist never crashes a UI handler.
function readRaw(tier: StorageTier, key: string): string | null {
  if (!browser) return null;
  try {
    if (tier === 'local') return localStorage.getItem(key);
    if (tier === 'session') return sessionStorage.getItem(key);
    return new URL(window.location.href).searchParams.get(key);
  } catch {
    return null;
  }
}

function writeRaw(tier: StorageTier, key: string, value: string | null) {
  if (!browser) return;
  try {
    if (tier === 'local') {
      if (value == null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
      return;
    }
    if (tier === 'session') {
      if (value == null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, value);
      return;
    }
    const url = new URL(window.location.href);
    if (value == null) url.searchParams.delete(key);
    else url.searchParams.set(key, value);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    /* ignore quota / private-mode / blocked-storage failures */
  }
}

export type PersistentState<T> = {
  value: T;
  reset(): void;
};

export function createPersistentState<T>(opts: {
  key: string;
  tier: StorageTier;
  codec: Codec<T>;
  debounceMs?: number;
}): PersistentState<T> {
  let value = $state<T>(opts.codec.decode(readRaw(opts.tier, opts.key)));
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function clearPending() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  }

  function flush(next: T) {
    const encoded = opts.codec.encode(next);
    writeRaw(opts.tier, opts.key, encoded);
  }

  function schedulePersist(next: T) {
    clearPending();
    if (opts.debounceMs != null && opts.debounceMs > 0) {
      debounceTimer = setTimeout(() => flush(next), opts.debounceMs);
      return;
    }
    flush(next);
  }

  return {
    get value() {
      return value;
    },
    set value(next: T) {
      value = next;
      schedulePersist(next);
    },
    reset() {
      // Drop any debounced write so a stale value can't land after the reset.
      clearPending();
      const def = opts.codec.decode(null);
      value = def;
      flush(def);
    }
  };
}

export type PersistentRecord<T extends object> = {
  [K in keyof T]: T[K];
} & {
  reset(): void;
  snapshot(): T;
};

export function createPersistentRecord<T extends object>(opts: {
  key: string;
  tier: 'session' | 'local';
  codec: Codec<T>;
  defaults: T;
}): PersistentRecord<T> {
  // Persist on each mutation (in the field setters / reset) rather than via an internal $effect:
  // $effect can only run inside a component-init context, so an $effect here would throw
  // `effect_orphan` the moment this factory is called outside component init (e.g. from a
  // .svelte.ts controller). Setter-based persistence has no such constraint and matches
  // `createPersistentState`.
  let record = $state<T>(browser ? opts.codec.decode(readRaw(opts.tier, opts.key)) : { ...opts.defaults });

  function persist() {
    writeRaw(opts.tier, opts.key, opts.codec.encode(record));
  }

  function snapshot(): T {
    return { ...record };
  }

  function reset() {
    record = { ...opts.defaults };
    persist();
  }

  const keys = Object.keys(opts.defaults) as (keyof T)[];
  const accessors: Record<string, unknown> = { reset, snapshot };

  for (const key of keys) {
    Object.defineProperty(accessors, key, {
      enumerable: true,
      get() {
        return record[key as keyof T];
      },
      set(next: T[keyof T]) {
        record = { ...record, [key]: next };
        persist();
      }
    });
  }

  return accessors as PersistentRecord<T>;
}
