# Behavioral Primitives

> **The keystone.** One good HTTP transport exists (`api/client.ts` →
> `apiRequest` — base URL, JSON, abort+timeout, workspace header), but **no abstraction for
> consuming it**. The `loading → try → catch → finally` envelope is hand-rolled across **~38
> files**; there are **0** shared resource/state/poller helpers. The team already proved the
> pattern (`useTableSort`, `useTableFilters`) — these extend it to the async/state half.
>
> New home: `src/lib/state/` (sibling to `components/page/table/use-*`). All factories expose
> reactive values through **getters** (never return a raw rune), per the **svelte-best-practice**
> skill's §11.1 rule — the same convention every controller in
> `features/**/state/*.svelte.ts` already follows.

> **Anchors use `file → symbol`, not line numbers** — earlier drafts pinned line numbers that
> drifted 15–55 lines within weeks. When you implement, grep for the symbol; don't trust a line.

---

## How to read this doc

Each section is: **problem (with verified evidence) → proposed API → implementation skeleton →
acceptance criteria.** The skeletons are starting points, not finished code — they encode the
decisions (error convention, teardown ownership, getter exposure) so a first implementation
doesn't re-derive them. Build in the order of the [Rollout](#rollout) section.

### Shared types you'll reference

```ts
// Already exists — import, don't redefine. src/lib/ui/toast-types.ts
type ToastKind = 'success' | 'error' | 'info' | 'warning';
type Notify = (kind: ToastKind, message: string) => void;

// New, lives in src/lib/state/types.ts
interface Resource<T> {
  readonly data: T;
  readonly loading: boolean;
  readonly error: string | null;
  readonly loaded: boolean;            // true once the first load() settles (ok or error)
  load(opts?: { silent?: boolean }): Promise<void>;
  reset(): void;
}

// A total, validating, never-throwing string<->T converter (see §2).
interface Codec<T> {
  decode(raw: string | null): T;       // null/garbage -> default, never throws
  encode(value: T): string | null;     // null result => remove the key
}

// Per-field schema for a JSON-backed record (see §2). Each field is independently
// validated; one bad field falls back to its default without nuking the whole record.
type FieldSchema<T> = { [K in keyof T]: Codec<T[K]> };
```

---

## 1. `createResource` / `createListResource` / `createMutation`

**Problem.** Every controller re-declares `loading`/`error` `$state` + the same try/catch. The
`err instanceof Error ? err.message : '…'` fallback alone appears **113× across 38 files**
(was 111×). The exact carbon-copy is `loadProviders` /​ `loadModels` in
`catalog-controller.svelte.ts → loadProviders`/`loadModels` (`providersLoading = true; … catch
{ providersError = err instanceof Error ? err.message : '…' } finally { providersLoading =
false }`), repeated for providers, models, characters, chat-channels, active-providers, and the
workspace store. The CRUD envelope (`busy → api → notify(success) → reset → reload → catch
notify(error)`) recurs across `workspace-store.svelte.ts` ~7×. Single-selection +
reconcile-after-reload is reimplemented 4+× (`logs activeRowKey`, `knowledge-browse
activeDocumentId`, `chat-channels selectedChannelId`, `graph-runs activeRunId`).

**Also cleans up a latent bug.** `apiRequest` **throws** on `!ok`
(`client.ts → apiRequest`, the `if (!response.ok || !payload.ok) throw` guard — currently
line 81), yet `graph-runs-controller.svelte.ts` (`loadRunDetail`, `resolveLangsmithUrl`, and a
third site — the `if (response.ok && response.data)` checks, currently `:345/:352/:418`) and
`memories-controller.svelte.ts` (`:167/:174`) still gate on `if (response.ok &&
response.data)` with **no else** — dead branches guarding an impossible failure path. A 3rd
convention (a `Result`-type union, `{ ok: true; … } | { ok: false; error }`) lives in
`graph-runs-ledger-service.ts`. Migrating onto `createResource` deletes the dead branches and
unifies on the **one** error convention: *the loader throws, the resource catches.*

### API

```ts
createResource<T>(
  loader: () => Promise<T>,
  opts?: { initial: T; errorPrefix?: string }
): Resource<T>;

createListResource<Row, Id = string>(
  loader: () => Promise<Row[]>,
  opts: { getId: (r: Row) => Id; errorPrefix?: string }
): Resource<Row[]> & {
  readonly selectedId: Id | null;
  readonly selected: Row | null;
  select(id: Id | null): void;
  reconcileSelection(): void;          // drop selection if the row vanished after reload
};

createMutation(
  fn: (...args: never[]) => Promise<unknown>,
  opts: { notify: Notify; successMsg?: string; errorPrefix?: string; onDone?: () => Promise<void> }
): { readonly busy: boolean; run(...args: never[]): Promise<void> };
```

### Implementation skeleton

```ts
// src/lib/state/create-resource.svelte.ts
export function createResource<T>(loader: () => Promise<T>, opts: { initial: T; errorPrefix?: string }): Resource<T> {
  let data = $state<T>(opts.initial);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  async function load(o?: { silent?: boolean }) {
    if (!o?.silent) loading = true;          // silent refetch keeps the old data visible
    error = null;
    try {
      data = await loader();                 // loader throws on failure (apiRequest already does)
    } catch (err) {
      error = err instanceof Error ? err.message : (opts.errorPrefix ?? 'Request failed.');
      // NOTE: do NOT reset `data` here — a failed silent refresh must not blank the table.
    } finally {
      loading = false;
      loaded = true;
    }
  }

  return {
    get data() { return data; },           // getters, per §11.1 — never `return data` as a field
    get loading() { return loading; },
    get error() { return error; },
    get loaded() { return loaded; },
    load,
    reset() { data = opts.initial; error = null; loaded = false; }
  };
}
```

`createListResource` wraps `createResource<Row[]>` and adds `selectedId` `$state` plus a
`reconcileSelection()` that runs after each load: `if (selectedId != null &&
!data.some(r => getId(r) === selectedId)) selectedId = null`. `createMutation` owns a `busy`
flag and the `try { await fn(); notify('success', successMsg); await onDone?.() } catch (err) {
notify('error', errorPrefix-fallback) } finally { busy = false }` envelope — note it takes
`notify` as an **explicit dependency** (decision below).

### Acceptance criteria

- A failed `load({ silent: true })` sets `error` but **leaves `data` unchanged** (regression
  test the current code lacks).
- After migrating `catalog-controller`, `npm run check` is clean and the
  `if (response.ok && response.data)` dead branches in graph-runs/memories are **gone**, not
  left dangling.
- `createListResource.reconcileSelection()` clears a selection whose row disappeared, and
  preserves one whose row remains.

## 2. `createPersistentState` + codecs

**Problem.** Tab prefs are shared (`createTabPreferences`, used by ~7 feature pref modules), but
**value/UI state is hand-wired**. `create-graph-options-state.svelte.ts` wires **~27 fields** ×
(state + getter + setter + snapshot line + reset line) ≈ **276 lines**;
`logs-preferences.svelte.ts` ≈ **252 lines**, including a hand-rolled
`JSON.parse`-in-try/catch-then-validate-each-field block (`createLogsPreferences →
hydrateFromSession`). That `JSON.parse → validate` idiom recurs across **~13 modules**; the
"read map → set/delete key → write map" routine is copied 3×.

### API

```ts
type Codec<T> = { decode(raw: string | null): T; encode(value: T): string | null };

enumCodec<T extends string>(allowed: readonly T[], def: T): Codec<T>;
intCodec(o: { min?: number; max?: number; default: number }): Codec<number>;
boolCodec(def: boolean, encoding?: 'bool' | 'bool01'): Codec<boolean>;   // bool01 retires the '1'/'0' fork
jsonCodec<T>(schema: FieldSchema<T>, defaults: T): Codec<T>;
keyedMap<V>(value: Codec<V>): Codec<Record<string, V>>;                  // replaces the 3 map routines

createPersistentState<T>(opts: {
  key: string; tier: 'url' | 'session' | 'local'; codec: Codec<T>; debounceMs?: number;
}): { value: T /* $state getter/setter */; reset(): void };

createPersistentRecord<T extends object>(opts: {
  key: string; tier: 'session' | 'local'; schema: FieldSchema<T>; defaults: T;
}): T & { reset(): void; snapshot(): T };   // collapses graph-options (276→~30) and logs prefs (252→~40)
```

### Implementation skeleton (the two codecs the rest build on)

```ts
// src/lib/state/codecs.ts — every codec is TOTAL: bad input -> default, NEVER throws.
export function enumCodec<T extends string>(allowed: readonly T[], def: T): Codec<T> {
  return {
    decode: (raw) => (raw != null && (allowed as readonly string[]).includes(raw) ? (raw as T) : def),
    encode: (v) => v
  };
}

export function jsonCodec<T>(schema: FieldSchema<T>, defaults: T): Codec<T> {
  return {
    decode(raw) {
      if (raw == null) return defaults;
      let parsed: unknown;
      try { parsed = JSON.parse(raw); } catch { return defaults; }   // the idiom, written ONCE
      const obj = (parsed ?? {}) as Record<string, string | null>;
      const out = { ...defaults };
      for (const k in schema) out[k] = schema[k].decode(obj[k] ?? null);  // per-field fallback
      return out;
    },
    encode(value) {
      const obj: Record<string, string | null> = {};
      for (const k in schema) obj[k] = schema[k].encode(value[k]);
      return JSON.stringify(obj);
    }
  };
}
```

`createPersistentState` picks the backing store from `tier` (`url` →
`URLSearchParams`/`history.replaceState`; `session` → `sessionStorage`; `local` →
`localStorage`), hydrates `value` via `codec.decode(store.get(key))` on creation, and on every
set writes `codec.encode(value)` (debounced if `debounceMs`), removing the key when `encode`
returns `null`. This carries the **existing** tier policy forward as an explicit selector —
keys still live in `preferences/keys.ts` (no change there; it's good).

### Acceptance criteria

- A corrupt `sessionStorage` value (non-JSON, or one bad field) decodes to the default
  **without throwing** and without discarding the *other* fields.
- Round-trip: `decode(encode(v)) === v` for each codec across boundary values (min/max for
  `intCodec`, every member for `enumCodec`).
- `create-graph-options-state` and `logs-preferences` rebuilt on `createPersistentRecord`
  produce byte-identical stored payloads to today (snapshot test before/after).

## 3. `createPoller` + unified teardown

**Problem.** There are **≥7 bespoke `setInterval` sites across 6 modules** (was reported as
5): `metrics-controller.svelte.ts → startPolling`, `graph-runs-controller.svelte.ts`
(interval `setInterval(poll, 2500)`), `logs-page-lifecycle.ts → setupLogsPageRuntime`,
`chat-messages-engine.svelte.ts` (**two** intervals), plus two dialogs
(`ChatMessageComposer.svelte`, `KnowledgeDocumentReingestDialog.svelte`). `graph-runs`'
`poll()` is **missing the re-entrancy guard** that `metrics` has (`metrics`:
`if (polling) return; polling = true; … finally { polling = false }`; `graph-runs poll()`:
none — a slow tick can overlap the next). None pause on tab-hidden, though the SSE layer
already does.

### The teardown decision (read before coding)

A factory in a plain `.svelte.ts` module **cannot call `$effect` for itself** — `$effect` only
registers against the component-init/effect context of *whoever calls the factory*, and
controllers here are often created lazily, not synchronously during a component's init. So
`createPoller` must **not** try to "clean itself up via `$effect`." Instead it follows the
pattern this codebase already uses everywhere: **`start()` returns a disposer; the component
wires it into `$effect`,** and Svelte runs the returned cleanup on unmount.

```
metrics-controller.startPolling()  ──returns──▶  () => clearInterval(timer)
        ▲                                              │
        │ component:                                   ▼
   $effect(() => ctrl.startPolling())  ◀── Svelte calls the returned disposer on teardown
```

This mirrors `metrics-controller → startPolling` (returns `() => clearInterval`),
`setupMetricsTabRuntime`, and `setupLogsPageRuntime` (returns a teardown that
`clearInterval`s + removes listeners), all consumed today via `$effect(() => setup(...))` in
the `.svelte` page. `createPoller` makes the missing guard and the hidden-tab pause
**structural** instead of per-call.

### API

```ts
createPoller(
  fn: () => Promise<void>,
  opts: { intervalMs: number; pauseWhenHidden?: boolean; immediate?: boolean }
): {
  start(): () => void;   // begins polling; RETURNS the disposer — wire via $effect(() => poller.start())
  stop(): void;
};
```

### Implementation skeleton

```ts
// src/lib/state/create-poller.svelte.ts
export function createPoller(fn: () => Promise<void>, opts: { intervalMs: number; pauseWhenHidden?: boolean; immediate?: boolean }) {
  let timer: ReturnType<typeof setInterval> | null = null;
  let inFlight = false;                       // the re-entrancy guard graph-runs lacks

  async function tick() {
    if (inFlight) return;                     // never overlap a slow tick with the next
    if (opts.pauseWhenHidden && document.hidden) return;
    inFlight = true;
    try { await fn(); } finally { inFlight = false; }
  }

  function start() {
    if (opts.immediate) void tick();
    timer = setInterval(() => void tick(), opts.intervalMs);
    // optional: visibilitychange listener to skip ticks while hidden (above guard already does)
    return stop;                              // <-- caller passes this to $effect
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  return { start, stop };
}
```

A sibling `createEventSubscription(connect)` can unify the SSE-disposer ownership the same way
(connect returns a disposer; component wires it via `$effect`).

### Acceptance criteria

- A `fn` that takes longer than `intervalMs` never runs concurrently (re-entrancy guard
  observable in a test with a deferred promise).
- `start()`'s returned disposer stops the interval; calling it twice is safe.
- With `pauseWhenHidden`, no `fn` call fires while `document.hidden` is true.

---

## Resolved design questions

- **Does `createMutation` take the notifier as a dependency?** **Yes — explicit dependency
  injection.** Every controller already receives `notify: Notify` as a constructor argument
  (e.g. `createCatalogController(notify)`), so `createMutation({ notify })` matches the
  established wiring and keeps the primitive testable (pass a spy). It is **not**
  notifier-agnostic and does **not** reach for a global toast host. This also resolves the
  open item that pointed at the toast-host decision in [00-overview.md](00-overview.md) §4 —
  the primitive doesn't depend on it.
- **Where does teardown live for `createPoller`?** In the **caller's `$effect`**, via a
  returned disposer — see §3. The primitive owns the timer + guard + hidden-pause; the
  component owns the lifetime.

## Rollout

1. Build `createResource` + `createMutation` + their tests (`src/lib/state/`).
2. Migrate **`catalog` end-to-end first** (small, self-contained; it's the canonical
   duplicate). Concretely, replace `catalog-controller`'s `loadProviders`/`loadModels` with
   `createResource(listCatalogProviders, { initial: [] })` /
   `createResource(() => listCatalogModels(catalogFetchFilters()), { initial: [] })`, and the
   `reloadBundledCatalog` envelope with `createMutation`. Then expose `providers.data` etc.
   through the existing getters.
3. Confirm `npm run check` + unit tests green and behavior identical in the dev UI
   (`http://localhost:5173`).
4. Add `createPersistentState`/codecs (§2) and rebuild `graph-options` + `logs-preferences`.
5. Add `createPoller` (§3) and convert the 6 polling modules, deleting their bespoke
   `setInterval` + guards.

The mega-controller facade decomposition (graph-runs/knowledge — owned by
[`../admin-frontend-refactor-plan.md`](../admin-frontend-refactor-plan.md)) gets much cheaper
once these exist.
