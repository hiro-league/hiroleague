/**
 * A small reactive "toggle set" rune for the trace dialogs' disclosure state — which stage
 * cards are collapsed, which prompts / raw-JSON blocks are open, which long cells are expanded.
 * Both dialogs hand-rolled the same `new Set(...)` / has / add / delete dance up to five times;
 * this centralises it (always replacing the Set so Svelte tracks the mutation reactively).
 *
 * Generic over the key type: stage indices (number) for collapse/prompt/json, composite cell
 * keys (string) for the retrieval clamp cells.
 */
export type ToggleSet<T> = {
  /** The live Set — read this in `$derived`/markup so changes are tracked. */
  readonly value: Set<T>;
  has(key: T): boolean;
  /** Flip a single key in/out of the set. */
  toggle(key: T): void;
  /** Add every key (e.g. collapse-all over a phase/lane's stage idxs). */
  add(keys: Iterable<T>): void;
  /** Remove every key (e.g. expand-all). */
  remove(keys: Iterable<T>): void;
  /** Empty the set. */
  clear(): void;
  /** Replace the whole set (e.g. re-seed all-collapsed on a new trace). */
  replace(keys: Iterable<T>): void;
};

export function createToggleSet<T>(initial: Iterable<T> = []): ToggleSet<T> {
  let set = $state<Set<T>>(new Set(initial));
  return {
    get value() {
      return set;
    },
    has: (key: T) => set.has(key),
    toggle(key: T) {
      const next = new Set(set);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      set = next;
    },
    add(keys: Iterable<T>) {
      const next = new Set(set);
      for (const k of keys) next.add(k);
      set = next;
    },
    remove(keys: Iterable<T>) {
      const next = new Set(set);
      for (const k of keys) next.delete(k);
      set = next;
    },
    clear() {
      set = new Set();
    },
    replace(keys: Iterable<T>) {
      set = new Set(keys);
    }
  };
}
