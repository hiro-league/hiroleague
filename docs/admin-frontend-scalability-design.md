# Admin Frontend — Scalability & Shared-Abstraction Design

> **What.** A forward-looking architecture review of `admin_frontend/`, aimed at the
> *next* order of leverage: the shared **behavioral / logic primitives**, **design
> tokens**, and **drift-prevention guardrails** that future features will lean on. Where
> the companion [`admin-frontend-refactor-plan.md`](admin-frontend-refactor-plan.md) asks
> *"does each existing page conform to the conventions?"* (file size, tests, vertical
> slices), this doc asks *"what shared abstractions are missing, so that the 15th–30th
> feature costs less code and the conventions hold **structurally** rather than by
> discipline?"*
>
> **Verdict.** The **presentational layer is unified** and the refactor round paid off —
> page chrome, table primitives, the one dialog family, `Inline*` feedback,
> `admin-tokens.ts`, data-driven `nav.ts`, thin routes, vertical-slice folders, and a
> Svelte-free graph engine are all adopted correctly. The unifying gap is one level
> down: **the behavioral layer has almost no shared abstractions.** You unified *what
> things look like*, not *what things do* — so loading/error/CRUD/polling/persistence is
> hand-rolled in every controller. Closing that gap is the highest-leverage work left.
>
> **Mode.** Initial development — **no backward compatibility / no migration / no
> wrappers** (repo rule, explicitly abided). Introducing a shared primitive means
> migrating call sites to it **directly** and deleting the old hand-rolled code, not
> shimming a compatibility layer.
>
> **Status.** 🟡 **Proposed — awaiting review.** Nothing here is built yet. §9 lists the
> open decisions that need the owner's call before execution.
>
> **How to use this doc.** §1 is the diagnosis + coverage map. §2–§5 are the proposed
> work in four tiers, ranked by leverage (not effort); each item carries problem →
> evidence → proposed shape → impact. §6 is the recommended sequence. §7 is what to
> **preserve**. §8 is the verified evidence index. §9 is open questions for the owner.

---

## 1. Diagnosis — two layers, one of them empty

The codebase has a mature **presentational primitive** library and an almost-empty
**behavioral primitive** library. The team already proved the behavioral pattern works
(`useTableSort`, `useTableFilters`, `createTabPreferences`) — it just never extended it to
the async/state/persistence half, which is where the real repetition lives.

```
ADMIN FRONTEND — abstraction coverage

  PRESENTATIONAL LAYER  (what things look like)      BEHAVIORAL LAYER  (what things do)
  ──────────────────────────────────────────        ──────────────────────────────────
  ✓ AdminPageHeader / TabStrip / SectionCard         ✓ useTableSort / useTableFilters
  ✓ AdminTableShell / FilterBar / MasterDetail       ✓ createTabPreferences
  ✓ Dialog family / FormField / Inline* feedback     ✗ createResource / createMutation     ← MISSING
  ✓ Toast / Markdown / OrderedModelPicker            ✗ createListResource (selection)      ← MISSING
  ✓ admin-tokens.ts (layout/chrome classes)          ✗ createPersistentState (codec)       ← MISSING
  ✗ status color tokens (ok/warn/info)      ← GAP    ✗ createPoller / event-subscription   ← MISSING
  ✗ DetailPanelShell / StatTile / CopyButton ← GAP

  Net: UI is unified; behavior is copy-pasted — 111 hand-rolled try/catch blocks,
       0 shared async/resource helpers, 5 bespoke setInterval pollers.
```

**The consequence for scaling:** every new feature re-pays the cost of loading/error
handling, selection-with-reconcile, persisted UI state, and status styling by hand. Each
copy is a place for behavior to drift and a place a cross-cutting fix (abort, retry,
tab-hidden pausing, dark-mode contrast) has to be applied N times instead of once.

---

## 2. Tier 1 — Build the missing logic-primitive layer (highest leverage)

This is the keystone tier. It is where the codebase pays the most as features multiply,
and it makes much of Tier 3 fall out cheaply.

### 1A. `createResource` + `createListResource` + `createMutation`

**Problem.** There is one good HTTP transport (`apiRequest` in `api/client.ts`, which
centralizes base URL, JSON, abort+timeout, and the workspace header) but **no abstraction
for *consuming* it.** Every controller re-declares `loading`/`error` `$state` and the same
`try → catch → finally` envelope around it.

**Evidence (verified).**
- The `err instanceof Error ? err.message : '…'` fallback appears **111 times across ~30
  files** (`grep -rn "instanceof Error ? " src/lib | wc -l`).
- **Zero** `createResource` / `createAsyncResource` / `createListController` /
  `createMutation` exist today.
- Carbon-copy loaders: `catalog-controller.svelte.ts:197` (`loadProviders`) & `:229`
  (`loadModels`); `characters-controller.svelte.ts:79` (`loadCharacters`);
  `chat-channels-controller.svelte.ts:163` (`loadChannels`);
  `active-providers-store.svelte.ts:80` & `workspace-store.svelte.ts:63` (both with a
  `{ silent }` variant). All the same state machine with renamed fields.
- CRUD mutation envelope (`busy=true → await api → notify(success) → reset → reload →
  catch notify(error) → finally busy=false`) recurs **7×** in `workspace-store`
  (`:151–273`) and again in `characters-controller` (`:219`), `chat-channels-controller`
  (`:235`), `active-providers-store` (`:138`).
- Single-selection + reconcile-after-reload ("selected id → derived selected row → drop
  selection when the row vanished") is reimplemented 4+ times: `logs-controller`
  (`activeRowKey`, `:119`/`:250`), `knowledge-browse` (`activeDocumentId`, `:198`/`:270`),
  `chat-channels-controller` (`selectedChannelId`, `:56`/`:169`), `graph-runs-controller`
  (`activeRunId`, `:71`/`:266`).

**Proposed shape** (new home `src/lib/state/`, mirroring the existing
`components/page/table/use-*` getter convention — expose `$derived` via getters per the
skill's gotcha §11.1):

```ts
// createResource — owns loading/error/data + a re-runnable loader
createResource<T>(loader: () => Promise<T>, opts?: { initial: T; errorPrefix?: string }): {
  readonly data: T; readonly loading: boolean; readonly error: string | null;
  readonly loaded: boolean;
  load(opts?: { silent?: boolean }): Promise<void>;   // try/catch/finally + Error-message fallback built in
  reset(): void;
}

// createListResource — adds list + single selection + reconcile on top
createListResource<Row, Id = string>(loader, opts: { getId: (r: Row) => Id }): Resource<Row[]> & {
  readonly selectedId: Id | null; readonly selected: Row | null;
  select(id: Id | null): void;
  reconcileSelection(): void;          // drop selection if the row disappeared after reload
}

// createMutation — the busy + notify + refetch wrapper
createMutation(fn, opts: { notify: Notify; successMsg?: string; errorPrefix?: string; onDone?: () => Promise<void> }): {
  readonly busy: boolean; run(...args: unknown[]): Promise<void>;
}
```

A controller's `loadProviders` then becomes one line:
`providers = createResource(listCatalogProviders, { initial: [] })`.

**Impact.** Collapses ~45 load/mutation handlers and all 111 catch blocks into
declarative one-liners, and gives **one** place to later add request-generation guards,
abort, retry, or backoff. Highest leverage in the review. Composes with (does not replace)
`useTableSort`/`useTableFilters`.

> **Note — also fixes a latent correctness bug.** `apiRequest` already *throws* on
> `!response.ok || !payload.ok` (`api/client.ts:81`). Yet `graph-runs-controller`
> (`:302`,`:309`,`:375`) and `memories-controller` (`:167`,`:174`) still gate on
> `if (response.ok && response.data)` **with no `else`** — dead branches that silently
> swallow the (now impossible) failure path. A third convention (a `Result`-type
> `{ ok, error }`) lives in `graph-runs-ledger-service.ts`. Migrating onto `createResource`
> deletes the dead branches and unifies on one error convention.

### 1B. `createPersistentState` + composable codecs

**Problem.** Tab preferences are already shared (`createTabPreferences` — 10/14 prefs files
reuse it; good). But **value/UI state has no abstraction** — it is hand-wired field by
field, and the "read string → JSON.parse in try/catch → validate per field → fall back to
defaults; stringify on write" idiom is copy-pasted.

**Evidence.**
- `state/graph/create-graph-options-state.svelte.ts` hand-wires **27 fields** ×
  (`$state` + getter + setter + a line in `snapshot()` + a line in `reset()`) ≈ **260
  lines** of pure mechanical repetition.
- `logs-preferences.svelte.ts` does the same for ~14 fields (`hydrateFromSession` `:43` +
  `persistToSession` `:77` re-list every field) ≈ **200 lines**.
- The `JSON.parse`-in-try/catch-then-validate shape appears in **8 functions** across
  `knowledge-graph-prefs.ts` (`readGraphOptions` `:195`), `graph-persistence.ts`
  (`readEdgeFilterModes` `:26`), `eval-prefs.ts` (`:22`/`:49`).
- The "read map → set/delete one key → write map" routine is copied **3×**
  (`eval-prefs.ts:32`, `knowledge-graph-prefs.ts:344`, `graph-persistence.ts:74`).
- Booleans are encoded **two different ways** — `storage.ts:18` uses `'true'/'false'`,
  while `chat-channels-ui-prefs.svelte.ts:22` and `chat-overlay-store.svelte.ts:19`
  hand-roll `'1'/'0'` (and re-implement the quota `try/catch`).

**Proposed shape.**

```ts
type Codec<T> = { decode(raw: string | null): T; encode(value: T): string | null }; // total, validating, never throws

const enumCodec = <T extends string>(allowed: readonly T[], def: T): Codec<T>;
const intCodec  = (o: { min?: number; max?: number; default: number }): Codec<number>;
const boolCodec = (def: boolean, encoding?: 'bool' | 'bool01'): Codec<boolean>;
const jsonCodec = <T>(schema: FieldSchema<T>, defaults: T): Codec<T>;   // replaces readGraphOptions/readEdgeFilterModes
const keyedMap  = <V>(value: Codec<V>): Codec<Record<string, V>>;        // replaces eval-corpus/answer-prompt/episode-sel maps

// one reactive, persisted scalar
createPersistentState<T>(opts: { key: string; tier: 'url' | 'session' | 'local'; codec: Codec<T>; debounceMs?: number }):
  { value: T /* $state getter/setter */; reset(): void };

// multi-field record — collapses graph-options & logs prefs
createPersistentRecord<T extends object>(opts: {
  key: string; tier: 'session' | 'local';
  schema: { [K in keyof T]: Codec<T[K]> }; defaults: T;
}): T & { reset(): void; snapshot(): T };   // auto getters/setters + persist-on-change
```

**Impact.** `create-graph-options-state` drops ~260 → ~30 lines; `logs-preferences`
~200 → ~40. Every *future* preference becomes one line with validation **guaranteed by
construction** instead of by remembering to write a try/catch. Carries the existing,
already-consistent `tier` (url/session/local) policy forward as an explicit selector.

> Add `bool01` to `storage.ts` and route the two `'1'/'0'` call sites through it; centralize
> the quota `try/catch` inside `writeLocalString` once.

### 1C. Semantic status-color tokens

**Problem.** "ok = green / warn = amber / error = red / info = sky" is an app-wide
convention with **no token**. It is re-expressed as raw Tailwind palette classes (each
with a hand-maintained `dark:` pair) **and**, in graph-runs, as raw hex in scoped styles —
so the same meaning uses several different shades and there is no single source of truth.

**Evidence.**
- ~100+ hardcoded status-color sites. `badge.svelte` is inconsistent with *itself*:
  `destructive` uses the `bg-destructive` token (`:?`) but `success`/`warning` use raw
  `emerald-500`/`amber-500` (`:18–20`).
- The identical amber warning-banner string
  `rounded-md border border-amber-500/30 bg-amber-500/10 … text-amber-700 dark:text-amber-300`
  is duplicated byte-for-byte in `KnowledgePage.svelte:75`, `EvalPage.svelte:95`, and three
  workspace dialogs.
- Raw hex for the *same* meanings in scoped styles: `ValidityPill.svelte:28` (`#16a34a`/
  `#dc2626`), `IngestPhaseStages.svelte:467` (`#b45309`/`#2563eb`/`#16a34a`),
  `GraphRunsRunDetailHeading.svelte:176` (node-type swatches). Raw hex is **theme-blind** —
  it renders identically in light and dark, a real contrast bug.
- The uppercase field-label kicker `font-sans text-xs font-semibold uppercase
  text-muted-foreground` recurs 8× in `CharacterViewPanel` / `CharacterResolvedBlock`.

**Impact.** Add `--success / --warning / --info` (+ node-type accent swatches) per theme to
`app.css`, wire into the `@theme inline` block (so `bg-success`/`text-warning` exist), add
`ADMIN_FIELD_KICKER` + an `<AdminAlert variant>` (or `ADMIN_ALERT_*` constants) to
`admin-tokens.ts`, and route `badge.svelte` / `ToastHost` / `InlineWarningAlert` /
graph-runs pills through them. One change retires ~140 hardcoded sites **and** closes the
dark-mode-contrast footgun. (Also drop the stale `, #64748b` fallbacks in `var(--…)` calls —
the vars are always defined on `:root`.)

---

## 3. Tier 2 — Fill the remaining presentational-primitive gaps

High-frequency "this should already be a component" cases.

| Missing primitive | Duplicated in | Win |
|---|---|---|
| **`DetailPanelShell`** (aside + bordered header + close + scroll body) + **`DetailFieldGrid`** | `GraphRunsNodeDetailPanel.svelte:62`, `LogsDetailPanel.svelte:44`, `KnowledgeGraphDetailPanel.svelte:295` | ~150 dup lines + scoped CSS → one component (parallels the just-landed `TraceDialogShell`) |
| **`use-copy.svelte.ts` + `CopyButton`** | copy-to-clipboard + "Copied!" timer hand-rolled 5×: `workspace-store.svelte.ts:322`, `devices-controller.svelte.ts:68`, `eval-traces.svelte.ts:170`, `LogsDetailPanel.svelte:33`, `KnowledgeAskPanel.svelte:211` (last gives *no* feedback) | uniform feedback, kills 5 timer state machines |
| **`StatTile` / `KpiCard`** | `DashboardPanel.svelte` inlines 3 KPI cards; `GraphRunsRunAggregateMetrics.svelte` has its own; `metrics/MetricCard` already exists but isn't shared | promote `MetricCard` up; DashboardPanel drops ~120 lines |
| Route stragglers through **`InlineEmptyState`** | ~9 hand-rolled empty-state blocks (3 in `KnowledgeAskPanel` alone, `:172`/`:179`/`:231`), retire the bespoke `MutedStatusLine` | retires the most-copied class string |
| **`destructive-outline` button variant** | `StderrLogButton.svelte:25`, `ChatMessageComposer.svelte:136`, `ChatMessagesToolbar.svelte:79` | one variant instead of 3 pasted class strings |

> Note: the three `border-destructive/50 … hover:bg-destructive/10` hits are destructive
> *button* styles (a legitimate variant), **not** inline-alert violations — the existing
> refactor plan §7 already flagged this. The fix is to add the variant, not to rewrite them
> as alerts.

---

## 4. Tier 3 — Structural consistency (decomposition + correctness)

Some of this overlaps the companion plan's file-size work; here the angle is **logic
structure**, not line count.

- **Adopt eval's facade-of-sub-controllers pattern for the mega-controllers.**
  `eval-model.svelte.ts` is the reference — a thin facade composing `eval-run` /
  `eval-setup` / `eval-corpus-picker` / `eval-results`. Apply it to
  `graph-runs-controller.svelte.ts` (673), `knowledge-ingest.svelte.ts` (535,
  scan + job-tracking + post-ingest graph-build + event-connection in one file), and
  `knowledge-browse.svelte.ts` (485). Tier 1A shrinks these substantially on its own; the
  facade split handles the rest. (Complements refactor-plan §2/§3, which target the
  *panels*; this targets the *controllers*.)
- **Extract `<StageGroupRenderer>`** — `IngestPhaseStages.svelte` (491) and
  `RetrievalLaneStages.svelte` (284) duplicate the StageCard-iteration + metadata-header
  skeleton. ⚠️ **Tension with refactor-plan §2 step 3**, which deliberately decided *not*
  to merge the stage tables because the per-stage table bodies genuinely diverge. The
  proposal here is narrower: extract only the **iteration shell** (StageCard loop + header)
  and inject each dialog's divergent table body as a snippet — keeping the schemas
  separate, honoring that decision. **Owner decision needed** (see §9) — possibly defer
  until a third trace type appears.
- **`createPoller` + unified `$effect`-owned teardown.** 5 bespoke `setInterval` loops
  (`metrics-controller:129`, `graph-runs-controller:514`, `logs-page-lifecycle:31`,
  `chat-messages-engine`, a dialog). `graph-runs` is **missing the re-entrancy guard**
  `metrics` has, and its interval **leaks if the returned `dispose()` isn't wired** (no
  `$effect` self-cleanup). One `createPoller(fn, { intervalMs, pauseWhenHidden })` that
  owns its timer + in-flight guard + `visibilitychange` pausing makes the leak structurally
  impossible and stops background tabs from polling (the SSE layer already pauses on hidden;
  pollers don't).
- **Cross-cutting cleanup (shell-level):**
  - Move the dashboard's controller/header logic out of `routes/+page.svelte:7` into a
    `features/dashboard/DashboardPage.svelte`, making routes **14/14** thin (it's the lone
    non-thin route, and the most likely template for the next one).
  - Extract the copy-pasted SSE "degraded" banner (`KnowledgePage.svelte:75` ≡
    `EvalPage.svelte:95`) into a shell-hosted `<LiveEventsHealthBanner>` (mirrors
    `ServerStartingBanner`).
  - Reconcile the **two parallel toast systems** — shell-global `ToastHost` in
    `AdminShell.svelte:312` **and** a per-page `createToastNotifier` + second `<ToastHost>`
    in 9 features. Decide on one (or document why the shell host is chat-only).
  - Extract the repeated **tab-plumbing ritual** (`create<X>Preferences()` →
    `onMount(initialize)` → `afterNavigate(syncActiveTabFromUrl)`), copied in ~6 tabbed
    pages, into a `createTabbedPage()` helper or `<TabbedAdminPage>` wrapper — so forgetting
    `syncActiveTabFromUrl` (which silently breaks back/forward) becomes impossible.

---

## 5. Tier 4 — Drift prevention (lock in the gains)

- **Codegen the backend-mirrored types.** `api/preferences.ts` hand-mirrors ~200 lines of
  `hirocli/domain/preferences.py`; `api/graph-runs.ts:73` keeps a hand-ordered column array
  "same order as the server" (silent mis-map risk if the backend reorders).
  `api/knowledge.ts:489` documents "shapes mirror serialize.py". FastAPI already emits
  OpenAPI; generate at least `WorkspacePreferences` and the serialize/graph-runs DTOs.
  Removes the documented 4-step manual-sync ritual (CLAUDE.md) and an entire class of
  silent shape-mismatch bugs.
- **Settle the controller-suffix convention.** `-controller` / `-store` / `-model` /
  `-engine` are used interchangeably for the same role. Proposal: `-controller` = page
  orchestrator, `-store` = genuinely cross-page singleton (`active-providers`, `workspace`),
  retire `-model`/`-engine` as a naming. Document it in the `svelte-best-practice` skill so
  it stops drifting.
- **Encode the conventions as guardrails.** Most divergences are greppable
  (`border-destructive` raw blocks, `h-10 rounded-md border border-input` input soup,
  hardcoded status colors, `mx-auto` page wrappers, page-local `setTimeout`+toast). A few
  ESLint/Stylelint rules or a CI grep keeps the conventions from eroding as contributors
  multiply — the difference between conventions held by discipline and held by tooling.
- **Shared `queryString()` + named timeout tiers** in `api/client.ts` — 4 hand-rolled
  empty-skipping `URLSearchParams` builders (`catalog.ts:111`, `knowledge.ts:441`,
  `logs.ts:135`, `eval.ts:98`) and scattered magic-number timeouts
  (`TIMEOUTS.quickProbe / standard / heavyLLM`). Small, but self-documenting.

---

## 6. Recommended sequence

```
Tier 1A (createResource / createMutation)  ──► unblocks Tier 3 controller decomposition
        │                                        + deletes the dead response.ok branches
        ├─ Tier 1C (status tokens)          ──► standalone; retires ~140 sites, fixes dark mode
        └─ Tier 1B (persistent-state codec) ──► standalone; collapses the prefs layer
                    │
                    ▼
        Tier 2 primitives (DetailPanelShell, use-copy, StatTile)  ──► quick, visible wins
                    │
                    ▼
        Tier 3 (facade controllers, createPoller, shell cleanup, StageGroupRenderer?)
                    │
                    ▼
        Tier 4 (type codegen, naming, lint guardrails, query/timeout helpers)
```

**Start with 1A.** It is the keystone: the mega-controller decomposition, the dead-branch
fix, and the polling/teardown unification all get dramatically cheaper once the
resource/mutation primitives exist. 1B and 1C are independent and can run in parallel.

A good **proof-of-concept first step**: build `createResource`/`createMutation`, migrate
**one** controller end-to-end (`catalog` is small and self-contained), confirm `npm run
check` + tests stay green and behavior is identical, then roll the pattern out.

---

## 7. What to preserve (do not disturb)

These are done right and are the templates to copy — churning them buys nothing:

- **The presentational primitive layer** — `AdminPageHeader`, table primitives, the one
  dialog family, `Inline*` feedback, `admin-tokens.ts`, `SectionCard`.
- **Data-driven navigation** — a new page is a one-line registration in `shell/nav.ts`;
  routes are thin shells (13/14).
- **The graph canvas engine is 100% Svelte-free** — `knowledge/graph/engine/` has zero
  rune/`svelte` imports; all reactivity lives in `state/graph/graph-engine-bridge.svelte.ts`.
  Exemplary separation.
- **`TraceDialogShell` + `ExpandCollapseButtons`** already de-duplicated the trace-dialog
  chrome (refactor-plan §2 executed).
- **The `create*()` factory + getter convention** (skill §11.1) is followed everywhere —
  the new primitives must expose getters the same way.
- **Centralized storage keys** (`preferences/keys.ts`, clean `hiro.admin.*` namespace, no
  collisions) and the **explicit URL-vs-session tier policy** — extend them, don't rework.
- **eval's facade-of-sub-controllers** (`eval-model.svelte.ts`) — the reference for Tier 3.

---

## 8. Evidence index (verified)

| Claim | Check | Result |
|---|---|---|
| Hand-rolled error-fallback idiom | `grep -rn "instanceof Error ? " src/lib \| wc -l` | **111** |
| Shared async/resource/state helpers | `grep -rn "createResource\|createAsyncResource\|createListController\|createMutation\|createPersistentState\|createPoller" src/lib` | **0** |
| Dead `response.ok` branches (apiRequest already throws) | `api/client.ts:81` throws; `graph-runs-controller.svelte.ts:302,309,375`, `memories-controller.svelte.ts:167,174` still gate on it | confirmed |
| `setInterval` poll loops | `grep -rln "setInterval" src/lib` | 5 feature loops (metrics, graph-runs, logs, chat, a dialog) |
| `create-graph-options-state` size | 27 hand-wired fields | ~260 lines |
| Hardcoded status-color sites | survey of `emerald/amber/red/sky` classes + raw hex | ~100+ |

App scale at review time: ~52K LOC frontend, 14 features. Largest: knowledge (14K / 97
files), eval (8.3K / 63), graph-runs (6.8K / 36), chat-channels (4.5K / 37).

---

## 9. Open questions for review

1. **Where do the new logic primitives live?** Proposed `src/lib/state/` (sibling to
   `components/page/table/use-*`). Agree, or prefer `$lib/runtime/` / co-located?
2. **`createMutation` + toast coupling** — should the mutation wrapper take the notifier as
   a dependency, or stay notifier-agnostic and let callers wire feedback? (Ties to the
   toast-host reconciliation in Tier 3.)
3. **`StageGroupRenderer`** — extract the iteration shell now, or honor refactor-plan §2's
   "don't merge stages" decision and defer until a third trace type exists?
4. **Toast architecture** — is the shell-global + per-page split intentional (chat overlay
   needs a host that survives navigation), or should it consolidate to one?
5. **Type codegen** — worth adding an OpenAPI→TS generation step to the frontend toolchain,
   or keep the manual mirror with a lint check that the shapes match?
6. **Scope of round 2** — do all four tiers in sequence, or land Tier 1 (the keystone)
   first and re-review before committing to 2–4?

---

> **Companion:** [`admin-frontend-refactor-plan.md`](admin-frontend-refactor-plan.md) —
> the per-feature file-size + test-coverage plan for the previous round. This doc assumes
> that round's structural cleanups and builds the shared-abstraction layer on top.
