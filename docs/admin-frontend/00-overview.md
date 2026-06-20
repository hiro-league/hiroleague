# Admin Frontend — Scalability Design (Overview)

> **What.** Forward-looking architecture notes for `admin_frontend/`, aimed at the *next*
> order of leverage: shared **behavioral primitives**, **search/filter** unification,
> **resilience**, **tokens**, and **drift-prevention**. Companion to
> [`../admin-frontend-refactor-plan.md`](../admin-frontend-refactor-plan.md) (the previous
> round: per-feature file-size + test coverage). This folder asks *"what shared
> abstractions are missing so the next features cost less code and conventions hold
> **structurally**?"* — not *"does each existing page conform?"*.
>
> **Style.** Pointer/example, not exhaustive. Each doc states the problem in a line or two,
> shows a concrete signature/example, and points at file:line evidence to research at
> implementation time. Reference tables (matrices, counts) are included where the analysis
> already produced them — they're evidence, not spec.
>
> **Mode.** Initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, explicitly abided). Introducing a primitive = migrate call sites directly and
> delete the old code.
>
> **Status.** 🟡 Proposed — awaiting review. Nothing built yet.

---

## 1. Diagnosis

The **presentational layer is unified** (page chrome, tables, dialogs, `Inline*`, tokens,
data-driven nav, thin routes, vertical slices, Svelte-free graph engine). The gap is one
level down: **the behavioral layer has almost no shared abstractions.** The team proved the
pattern works (`useTableSort`, `useTableFilters`, `createTabPreferences`) but never extended
it to async/state/persistence/search — where the real repetition lives.

```
PRESENTATIONAL (what things look like)         BEHAVIORAL (what things do)
─────────────────────────────────────         ───────────────────────────────
✓ AdminPageHeader / TabStrip / SectionCard     ✓ useTableSort / useTableFilters
✓ AdminTableShell / FilterBar / Dialog         ✓ createTabPreferences
✓ Inline* feedback / Toast / Markdown          ✗ createResource / createMutation     ← MISSING
✓ admin-tokens.ts (layout classes)             ✗ createPersistentState (codec)       ← MISSING
✗ status color tokens (ok/warn/info)  ← GAP    ✗ createTextSearch / one highlighter  ← MISSING
✗ DetailPanelShell / use-clipboard    ← GAP    ✗ createPoller / unified teardown     ← MISSING
                                               ✗ global error boundary / offline     ← MISSING

Net: UI unified; behavior copy-pasted — 111 try/catch blocks, 0 shared resource helpers,
     4 highlight implementations, ~9 search-predicate copies, 5 bespoke pollers.
```

## 2. The design docs (index)

| Doc | Theme |
|---|---|
| [search-and-filter.md](search-and-filter.md) | **Biggest duplication surface.** `lib/search/` (match + `<Highlight>` + `<SearchInput>` + `createTextSearch`) and filter-primitive upgrades. |
| [behavioral-primitives.md](behavioral-primitives.md) | `createResource` / `createMutation` / `createListResource` / `createPersistentState` (+codecs) / `createPoller`. |
| [cross-cutting-resilience.md](cross-cutting-resilience.md) | Global error boundary, unified server-unavailable state, SSE-banner dedup. (No frontend telemetry — see §5.) |
| [shared-components.md](shared-components.md) | Promote feature-local components to global; **and what to deliberately keep local.** |
| [styling-tokens.md](styling-tokens.md) | Semantic status tokens, field-kicker, `<AdminAlert>`. |
| [drift-prevention.md](drift-prevention.md) | Type-codegen idea, naming convention, lint/CI guardrails. (Guide set `01–04` follows.) |

## 3. What to preserve (do not disturb)

Done right; the templates to copy:
- **Presentational primitive layer** — `AdminPageHeader`, table primitives, the one Dialog family, `Inline*`, `admin-tokens.ts`.
- **Data-driven nav** — a page is a one-line `shell/nav.ts` registration; routes are thin (13/14).
- **Graph canvas engine is 100% Svelte-free** — `knowledge/graph/engine/` has zero rune/`svelte` imports; reactivity lives in `state/graph/graph-engine-bridge.svelte.ts`.
- **`TraceDialogShell` + `ExpandCollapseButtons`** already de-duplicated trace-dialog chrome.
- **`create*()` factory + getter convention** (skill §11.1) — new primitives must follow it.
- **`useTableFilters` / `useTableSort` / `createTabPreferences`** — the proof the pattern works.
- **Centralized keys** (`preferences/keys.ts`, no collisions) + explicit URL-vs-session policy.
- **eval's facade-of-sub-controllers** (`eval-model.svelte.ts`) — the reference for decomposition.
- **SSE is genuinely global** — only 2 `EventSource` singletons; eval rides the shared `knowledgeEventStream` (does *not* open its own). See [cross-cutting-resilience.md](cross-cutting-resilience.md).

## 4. Minor / opportunistic backlog

Real but small — one-liners, fix opportunistically, don't need their own doc:

- **Dual toast systems** — shell-global `ToastHost` (`AdminShell.svelte:312`) + a per-page `createToastNotifier` + 2nd `<ToastHost>` in 9 features. Decide on one (or document why the shell host is chat-only).
- **Dashboard route** is the lone non-thin route (`routes/+page.svelte:7` owns a controller/header) — move into `features/dashboard/DashboardPage.svelte` for 14/14 thin.
- **Tab-plumbing boilerplate** — `create<X>Preferences()` → `onMount(initialize)` → `afterNavigate(syncActiveTabFromUrl)` copied in ~6 pages; a `createTabbedPage()` helper removes the forget-`syncActiveTabFromUrl` footgun.
- **API helpers** — 4 hand-rolled empty-skipping `URLSearchParams` builders (`catalog.ts:111`, `knowledge.ts:441`, `logs.ts:135`, `eval.ts:98`) → one `queryString()`; scattered magic-number timeouts → named tiers (`TIMEOUTS.quickProbe/standard/heavyLLM`) in `api/client.ts`.
- **Blob/SSE base-URL** — workspace-header + base-URL logic re-implemented for blobs (`chat-channels.ts:217`) and both SSE singletons; export `apiUrl()`/`workspaceHeaders()`/`apiRequestBlob()` from `client.ts`.
- **`bool01` storage** — `chat-channels-ui-prefs.svelte.ts:22` + `chat-overlay-store.svelte.ts:19` re-roll `'1'/'0'` booleans + quota try/catch; add a `bool01` codec to `storage.ts`.
- **Scoped-style cleanups** — `MemoriesPanel` cell styles + `ValidityPill.svelte:28` re-implement plain utilities/colors → tokens (see [styling-tokens.md](styling-tokens.md)).
- **`1180px` magic breakpoint** — used twice (`AdminMasterDetail.svelte:26`, `MemoriesPanel.svelte:234`) for the same master/detail split; promote to a named breakpoint if a 3rd use appears.
- **Adherence stragglers** — ~9 hand-rolled empty states bypass `InlineEmptyState`; 3 destructive-outline buttons want a button variant (see [shared-components.md](shared-components.md)).

## 5. Considered & deferred (for later review)

Captured deliberately so they can be revisited — **not** in scope now:

- **Frontend logging / telemetry.** A `log.ts` seam + shipping logs somewhere is effectively a **new feature**, and backend logging is already good. The 8 existing `console.warn/error` swallow-and-log sites (eval-hydrate + graph secondary loads) are intentional and fine as-is. **Deferred.** Note: this is *distinct* from the global **error boundary** in [cross-cutting-resilience.md](cross-cutting-resilience.md), which is a resilience fix (recover from uncaught throws), not logging — that one **is** in scope.
- **`StageGroupRenderer`** (merge the `IngestPhaseStages` / `RetrievalLaneStages` stage-card skeleton in graph-runs). **Deferred** — conflicts with [`../admin-frontend-refactor-plan.md`](../admin-frontend-refactor-plan.md) §2 step 3, which deliberately decided *not* to merge the stage tables because the bodies genuinely diverge. Revisit only if a 3rd trace type appears.

## 6. Cross-referenced, not re-owned

- **Mega-controller decomposition** (`graph-runs-controller` 673, `knowledge-ingest` 535, `knowledge-browse` 485) via eval's facade pattern, and **oversized-file splits** — these are file-shape work owned by [`../admin-frontend-refactor-plan.md`](../admin-frontend-refactor-plan.md). The behavioral primitives here shrink those controllers substantially as a side effect; do the facade split there.

## 7. Open decisions (need ratification)

1. **Type-codegen** (OpenAPI→TS for `WorkspacePreferences` + serialize DTOs) — adopt the tooling, or keep the manual mirror + a lint check? See [drift-prevention.md](drift-prevention.md).
2. **Controller naming** — proposed `-controller` = page orchestrator, `-store` = cross-page singleton, retire `-model`/`-engine`. Needs your sign-off before the guide documents it.
