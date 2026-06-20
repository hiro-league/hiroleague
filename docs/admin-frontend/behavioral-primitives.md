# Behavioral Primitives

> **The keystone.** One good HTTP transport exists (`api/client.ts:apiRequest` —
> base URL, JSON, abort+timeout, workspace header), but **no abstraction for consuming it**.
> The `loading → try → catch → finally` envelope is hand-rolled **111× across ~30 files**;
> there are **0** shared resource/state/poller helpers. The team already proved the pattern
> (`useTableSort`, `useTableFilters`) — these extend it to the async/state half.
>
> New home: `src/lib/state/` (sibling to `components/page/table/use-*`). All expose `$derived`
> via getters, per the skill's §11.1 rule.

---

## 1. `createResource` / `createListResource` / `createMutation`

**Problem.** Every controller re-declares `loading`/`error` `$state` + the same try/catch.
The `err instanceof Error ? err.message : '…'` fallback alone appears **111×**.

Carbon-copy evidence: `catalog-controller.svelte.ts:197` & `:229`,
`characters-controller.svelte.ts:79`, `chat-channels-controller.svelte.ts:163`,
`active-providers-store.svelte.ts:80`, `workspace-store.svelte.ts:63`. CRUD envelope
(`busy → api → notify(success) → reset → reload → catch notify(error)`) recurs **7×** in
`workspace-store` (`:151–273`). Single-selection + reconcile-after-reload reimplemented 4+×
(`logs activeRowKey`, `knowledge-browse activeDocumentId`, `chat-channels selectedChannelId`,
`graph-runs activeRunId`).

```ts
createResource<T>(loader: () => Promise<T>, opts?: { initial: T; errorPrefix?: string }): {
  readonly data: T; readonly loading: boolean; readonly error: string | null; readonly loaded: boolean;
  load(opts?: { silent?: boolean }): Promise<void>;   // try/catch/finally + Error-message fallback built in
  reset(): void;
};

createListResource<Row, Id = string>(loader, opts: { getId: (r: Row) => Id }): Resource<Row[]> & {
  readonly selectedId: Id | null; readonly selected: Row | null;
  select(id: Id | null): void;
  reconcileSelection(): void;          // drop selection if the row vanished after reload
};

createMutation(fn, opts: { notify: Notify; successMsg?: string; errorPrefix?: string; onDone?: () => Promise<void> }): {
  readonly busy: boolean; run(...args: unknown[]): Promise<void>;
};
```

Then `loadProviders` becomes: `providers = createResource(listCatalogProviders, { initial: [] })`.

**Also cleans up a latent bug.** `apiRequest` *throws* on `!ok` (`client.ts:81`), yet
`graph-runs-controller.svelte.ts:302,309,375` and `memories-controller.svelte.ts:167,174`
still gate on `if (response.ok && response.data)` with **no else** — dead branches that
silently swallow the (impossible) failure path. A 3rd convention (`Result`-type) lives in
`graph-runs-ledger-service.ts`. Migrating onto `createResource` deletes the dead branches and
unifies on one error convention.

> **Open:** should `createMutation` take the notifier as a dependency, or stay
> notifier-agnostic? Ties to the toast-host decision in [00-overview.md](00-overview.md) §4.

## 2. `createPersistentState` + codecs

**Problem.** Tab prefs are shared (`createTabPreferences`), but **value/UI state is
hand-wired**. `create-graph-options-state.svelte.ts` wires **27 fields** × (state + getter +
setter + snapshot line + reset line) ≈ **260 lines**; `logs-preferences.svelte.ts` ≈ 200.
The `JSON.parse`-in-try/catch-validate idiom appears in **8 functions**; the "read map →
set/delete key → write map" routine is copied **3×**.

```ts
type Codec<T> = { decode(raw: string | null): T; encode(value: T): string | null }; // total, validating, never throws

enumCodec<T extends string>(allowed: readonly T[], def: T): Codec<T>;
intCodec(o: { min?: number; max?: number; default: number }): Codec<number>;
boolCodec(def: boolean, encoding?: 'bool' | 'bool01'): Codec<boolean>;   // bool01 retires the '1'/'0' fork
jsonCodec<T>(schema: FieldSchema<T>, defaults: T): Codec<T>;
keyedMap<V>(value: Codec<V>): Codec<Record<string, V>>;                   // replaces the 3 map routines

createPersistentState<T>(opts: { key: string; tier: 'url' | 'session' | 'local'; codec: Codec<T>; debounceMs?: number }):
  { value: T /* $state getter/setter */; reset(): void };

createPersistentRecord<T extends object>(opts: { key: string; tier: 'session' | 'local'; schema: { [K in keyof T]: Codec<T[K]> }; defaults: T }):
  T & { reset(): void; snapshot(): T };   // collapses graph-options (260→~30) and logs prefs
```

Carries the existing (already-consistent) `tier` policy forward as an explicit selector.
Keys stay in `preferences/keys.ts` (no change there — it's good).

## 3. `createPoller` + unified teardown

**Problem.** 5 bespoke `setInterval` loops (`metrics-controller.svelte.ts:129`,
`graph-runs-controller.svelte.ts:514`, `logs-page-lifecycle.ts:31`,
`chat-messages-engine.svelte.ts`, a dialog). `graph-runs` is **missing the re-entrancy
guard** `metrics` has, and its interval **leaks if the returned `dispose()` isn't wired**
(no `$effect` self-cleanup). Pollers don't pause on tab-hidden (the SSE layer already does).

```ts
createPoller(fn: () => Promise<void>, opts: { intervalMs: number; pauseWhenHidden?: boolean }):
  { start(): void; stop(): void };   // owns the timer + in-flight guard + visibilitychange; cleans up via $effect
```

Makes the leak structurally impossible and stops background tabs from polling. A sibling
`createEventSubscription(connect)` can unify the SSE-disposer ownership the same way.

---

## Rollout (suggestion)

Build `createResource` + `createMutation`, migrate **`catalog`** end-to-end first (small,
self-contained), confirm `npm run check` + tests green and behavior identical, then roll out.
The mega-controller facade decomposition (graph-runs/knowledge — owned by
[`../admin-frontend-refactor-plan.md`](../admin-frontend-refactor-plan.md)) gets much cheaper
once these exist.
