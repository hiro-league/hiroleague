# Admin Frontend — Refactor Status & Action Plan

> **What.** A best-practices audit of every page/feature under
> `admin_frontend/src/lib/features/`, measured against the project's
> [`svelte-best-practice`](../.claude/skills/svelte-best-practice/SKILL.md) skill
> (≤200-line page shells, vertical-slice folders, shared admin primitives,
> pure-logic extraction + tests, no duplicated pickers/markdown/`:global`).
>
> **Verdict.** The codebase is **structurally healthy** — routes are thin, the shared
> admin layer (`AdminPageHeader`, `createToastNotifier`, `Inline*`, table primitives,
> `SectionCard`) is adopted nearly everywhere, every `{@html}` is paired with a
> sanitizer, and `:global` is almost gone. The remaining work is concentrated in **a
> handful of oversized files** and **uneven test coverage**, not architectural rot.
>
> **Mode:** initial development — **no backward compatibility / no migration / no
> wrappers** (repo rule, explicitly abided). Decomposition below changes file shape
> only; behavior must stay identical.
>
> **How to use this doc.** §1 is the scorecard (14 numbered features). Each feature
> that is **not green** has its own numbered action section (§2+), sorted by priority,
> written so an agent can pick one up and execute it. Each section ends with a
> **Green criteria** checklist — finish those and the feature flips to 🟢. Green
> features (server, eval, preferences, characters, metrics, channels-devices,
> chat-channels) have **no action section** — leave them alone.

---

## 1. Status scorecard

Legend: 🟢 good / leave alone · 🟡 needs work · 🟠 heavy · 🔴 heavy refactor.
"Largest file" = biggest single `.svelte` in the feature. Shell = the `*Page.svelte`
composition root (target ≤200 lines).

| # | Feature | Files / Lines | Shell | Largest file | Tests | Folders | Status |
|---|---------|---------------|-------|--------------|-------|---------|--------|
| 1 | **server** | 18 / 918 | 47 | `WorkspaceRow` 157 | 3 | 4 ✅ | 🟢 Exemplary |
| 2 | **eval** | 23 / 3361 | 108 | `EvalAnswersPane` 392 | **13** | 7 ✅ | 🟢 Exemplary (best tests) |
| 3 | **preferences** | 30 / 2461 | 166 | `SingleModelPicker` 281 | 3 | 4 ✅ | 🟢 Good (20 SectionCards) |
| 4 | **characters** | 16 / 1670 | 126 | `CharacterResolvedBlock` 365 | 4 | 6 ✅ | 🟢 Good |
| 5 | **metrics** | 9 / 323 | (sub) | small | 3 | 3 ✅ | 🟢 Good |
| 6 | **channels-devices** | 6 / 380 | 58 | small | 4 | 4 ✅ | 🟢 Good |
| 7 | **chat-channels** | 15 / 1665 | 163 | `MessagesPanel` 233 | 3 | 7 ✅ | 🟢 Good |
| 8 | **catalog** | 6 / 662 | 72 | `ModelsTab` 186 | **0** | 3 ✅ | 🟡 Test gap |
| 9 | **memories** | 3 / 689 | 121 | `MemoriesPanel` **408** | 1 | 2 | 🟡 Big panel + `:global` |
| 10 | **logs** | 9 / 1391 | **199** | `LogsPanel` 356 | **0** | 2 | 🟡 Shell at limit, big panels, no tests |
| 11 | **dashboard** | 1 / 183 | n/a | `DashboardPanel` 183 | **0** | 2 | 🟡 Untested |
| 12 | **image-lab** | 4 / 282 | 43 | small | **0** | 1 | 🟡 Test gap |
| 13 | **knowledge** | **42 / 6043** | 92 | `KnowledgeGraphPanel` **611** | **4** | 6 ✅ | 🟠 Largest surface, under-tested |
| 14 | **graph-runs** | 17 / **3900** | (sub) | `IngestTraceDialog` **929** | 5 | 3 | 🔴 Two 600–929-line near-duplicate dialogs |

> `graph-runs`, `metrics`, and `dashboard` have **no `*Page.svelte` shell** because they
> are sub-features (graph-runs dialogs are consumed by `knowledge` and `eval`; dashboard
> is the home `+page.svelte`). That is correct per the skill's panel-portability rule.

### Files exceeding the ≤200-line target (the backlog, ranked)

| File | Lines | Feature |
|------|-------|---------|
| `graph-runs/GraphRunsIngestTraceDialog.svelte` | 929 | 14 |
| `knowledge/graph/KnowledgeGraphPanel.svelte` | 611 | 13 |
| `graph-runs/GraphRunsRetrievalTraceDialog.svelte` | 602 | 14 |
| `memories/MemoriesPanel.svelte` | 408 | 9 |
| `eval/answers/EvalAnswersPane.svelte` | 392 | 2 (🟢 — tested, leave) |
| `knowledge/graph/KnowledgeGraphDetailPanel.svelte` | 387 | 13 |
| `knowledge/graph/options/GraphOptionsViewSection.svelte` | 376 | 13 |
| `eval/execute/EvalExecutePane.svelte` | 374 | 2 (🟢 — tested, leave) |
| `characters/sections/CharacterResolvedBlock.svelte` | 365 | 4 (🟢 — tested, leave) |
| `logs/LogsPanel.svelte` | 356 | 10 |

### Priority order for the work below

1. **§2 graph-runs** (#14) — biggest single win; two near-duplicate dialogs.
2. **§3 knowledge graph** (#13) — largest surface, several 350–611-line files, under-tested.
3. **§4 logs** (#10) — shell at the limit, big panels, **zero tests despite a controller**.
4. **§5 memories** (#9) — 408-line panel + the only remaining `:global`.
5. **§6 test backlog** (#8 catalog, #12 image-lab, #11 dashboard) — pure modules with no tests.

---

## 2. graph-runs (#14) — 🔴 unify and decompose the two trace dialogs

**Files:** `admin_frontend/src/lib/features/graph-runs/`
- `GraphRunsIngestTraceDialog.svelte` (929)
- `GraphRunsRetrievalTraceDialog.svelte` (602)
- existing shared/: `StageCard.svelte`, `TraceTable.svelte`, `TraceTabs.svelte`,
  `ValidityPill.svelte`, `HighlightText.svelte`, `use-toggle-set.svelte.ts`,
  `trace-format.ts`, `ingest-trace-derive.ts`, `retrieval-trace-derive.ts`.

**Why it's red.** These two dialogs are the two largest `.svelte` files in the whole
admin UI. Helpers and stage cards are **already extracted** to `shared/`, so the bulk
is **markup** — and the two dialogs **mirror each other's chrome** (dialog shell,
header action row, expand/collapse-all controls, tab strip, per-section stage loop).
A bug fixed in one is easy to forget in the other.

**Do, in order (each step ships independently and leaves the app working):**

1. **Extract `<ExpandCollapseButtons>`** into `shared/`. Replaces the identical
   expand-all / collapse-all button pair at **Ingest 350–368** and **Retrieval 254–269**.
   Props: `{ onExpand, onCollapse }` (+ optional `disabled`). Smallest, highest-confidence win.

2. **Extract `<TraceDialogShell>`** into `shared/` — the `Dialog.Root` →
   `Dialog.Content` → `Dialog.Header` (title + actions row) → body → `Dialog.Footer`
   (Close) scaffold shared by **Ingest 320–407** and **Retrieval 227–298**. Use named
   snippets/slots for the parts that differ:
   - `headActions` — Ingest passes prev/next episode nav arrows + settings toggle;
     Retrieval passes the search box + bulk actions.
   - `description` — Ingest shows ingested text + config toggle; Retrieval shows the
     `TraceAnswers` (question/answer/ideal) block.
   - `body` — the per-section content (left in the calling dialog; see step 3).

3. **Do NOT merge the stage tables.** The per-stage table bodies genuinely diverge —
   Ingest has 3 structured-output kinds (rows/kv/scalar) + prompt/JSON toggles and **no
   search/sort**; Retrieval has 3 lane types (edge/node/episode) + per-column sort +
   search highlight + dropped-row strikethrough. Keep each dialog's stage loop and its
   local snippets (`viewTable`/`factVerdict`/`entitiesTable` in Ingest; `hl`/`sortTh`
   in Retrieval). Forcing one component here would be worse than the duplication.

4. **After steps 1–2**, Ingest should drop to roughly **≤650** and Retrieval to **≤480**.
   Ingest is still over target — split its **Result tab** (entities + facts tables,
   ~570–635) into `view/IngestResultTab.svelte` and the **per-phase stage loop**
   (~423–568) into `view/IngestPhaseStages.svelte`. Target Ingest ≤ ~300 in the shell.

**Green criteria**
- [ ] One `<TraceDialogShell>` + one `<ExpandCollapseButtons>` used by both dialogs (no mirrored chrome).
- [ ] `GraphRunsIngestTraceDialog.svelte` ≤ ~300 lines; `GraphRunsRetrievalTraceDialog.svelte` ≤ ~300 lines.
- [ ] No behavior change (episode nav, search, sort, expand/collapse, tabs all work as before).
- [ ] `npm run check` clean; existing `shared/*-derive.test.ts` and `use-toggle-set.svelte.test.ts` still pass.

---

## 3. knowledge graph (#13) — 🟠 decompose the graph panels, add tests for the pure core

**Files:** `admin_frontend/src/lib/features/knowledge/graph/` (panels) and
`knowledge/state/graph/` (controllers) and `knowledge/graph/engine/` (canvas).

This is the **largest feature** (42 files / 6043 lines) with only **4 test files**. Two
tracks: shrink the big panels (cheap, mechanical) and test the pure core (higher value).

### 3a. Shrink `KnowledgeGraphPanel.svelte` (611) — extract the options state

The script owns **24 slider/option `$state` variables** (~lines 61–92), their
**localStorage persistence `$effect`** (~255–284), and a 24-assignment
**`resetGraphOptions()`** (~288–316). That's the single biggest concern.

- Create `state/graph/create-graph-options-state.svelte.ts` exposing one reactive object
  (`get linkStrength()` … via getters per the skill's gotcha #1) plus `persist()` and
  `reset()`. Move lines 61–92 / 255–284 / 288–316 into it.
- The panel keeps engine glue (`createGraphEngineBridge`, onMount/onDestroy) and layout.
- Optionally split the floating control-button cluster (~400–445, 5 near-identical
  buttons) into a small `GraphCanvasControls.svelte`.
- **Target: panel ≤ ~350 lines.**

### 3b. Snippet-ify the repetitive option sections (low effort, big line wins)

- `options/GraphOptionsViewSection.svelte` (376): the two-knob slider block repeats **7×**
  (node size, node fade, zoom reveal, edge-label zoom/font, node-label zoom/font) and the
  button-group block repeats for search-focus / selection-focus. Introduce a
  `{#snippet rangeSliderSection(...)}` and `{#snippet buttonGroupSection(...)}` within the
  file. **Target ≤ ~150 lines.**
- `options/GraphOptionsFiltersSection.svelte` (289): same pattern — 3 button-group filters
  + 4 range/date sliders. Snippet-ify. **Target ≤ ~150 lines.**
- `KnowledgeGraphDetailPanel.svelte` (387): extract a `{#snippet}` for the header
  (icon+name+flip+close, ~238–273) and the summary+show-more block (~308–323).
- `KnowledgeGraphFilterDropdown.svelte` (250): move the `sorted`/`filtered`/`summary`/
  `placeholder` derivations (~58–79) into a pure `graph-filter-dropdown-helpers.ts` and
  unit-test them.

### 3c. Tests for the pure core (the real coverage gap)

Highest-value untested (or partially-tested) modules, ranked:

| Module | Lines | State | Add |
|--------|-------|-------|-----|
| `state/graph/graph-filter-pure.ts` | 320 | partial test | facet computations (`computeEdgeTypeFacets`, `computeNodeInstanceFacets`, matched/low-conn id sets) |
| `state/graph/graph-render-pure.ts` | 115 | partial test | label-sizing, node-fade, selection-focus paths |
| `state/graph/graph-persistence.ts` | 113 | none | URL ↔ localStorage round-trip of filter state |
| `graph/engine/graph-reconcile.ts` | 145 | none | live-SSE add/remove/update diffing (risk of dup/dropped nodes) |
| `graph/engine/graph-camera.ts` | 93 | none | zoom/pan math (extract pure fns first) |

**Green criteria**
- [ ] `KnowledgeGraphPanel.svelte` ≤ ~350; options sections ≤ ~150 each.
- [ ] Option/slider state + persistence lives in a `create-graph-options-state.svelte.ts` controller (getters, not shorthand).
- [ ] New tests: `graph-persistence.ts` round-trip + `graph-reconcile.ts` diffing, and the missing `graph-filter-pure` facet cases.
- [ ] `graph-filter-dropdown-helpers.ts` extracted + tested.
- [ ] `npm run check` clean; graph still renders/filters/searches identically.

---

## 4. logs (#10) — 🟡 keep the shell under the limit, decompose panels, add the missing tests

**Files:** `admin_frontend/src/lib/features/logs/`. **Zero test files today**, and the
shell sits exactly at the 200-line ceiling.

### 4a. Pull the shell back from the edge

`LogsPage.svelte` (199): move the **tab-descriptor array literal** (~39–42) into
`shared/logs-page-config.ts` and fold the tiny `openLogsFolder` handler (~44–46) into the
button or the controller. **Target ≤ ~175.**

### 4b. Decompose the heavy panels

- `LogsPanel.svelte` (356): extract the first toolbar row (level filter + search + pause +
  time-window + detail toggle + clear + collapse, ~163–288) into
  `LogsToolbar.svelte`. **Target ≤ ~240.**
- `LogsTablePanel.svelte` (309): extract the message-scope cell (chip + ordinal + "filter
  by message" button, ~192–226) into `LogsTableMessageScopeCell.svelte` or a `{#snippet}`.
  **Target ≤ ~265.**
- `LogsFiltersPanel.svelte` (192): the 4 "select + label + clear button" pairs (Channel,
  Device, Method, plus the multi-selects) are near-identical — extract one
  `FilterSelectWithClear.svelte`. **Target ≤ ~120.**
- `LogsDetailPanel.svelte` (199): already clean — **leave it**.

### 4c. Tests (the real gap)

- `shared/logs-ui.ts` (268): `compareLogRows()` and `rowPassesFilters()` are pure,
  critical-path, and **untested** → add `logs-ui.test.ts`. This is the #1 logs task.
- Extract the **message-ordinal logic** currently buried in
  `state/logs-controller.svelte.ts` (~78–151: stable 1,2,3… per `scope_msg_id` + stripe
  alternation) into a pure `shared/logs-ordinal.ts` and test it.
- `shared/logs-page-lifecycle.ts` (41): test the `msg_id`-from-URL-overrides-session path.

**Green criteria**
- [ ] `LogsPage.svelte` ≤ ~175; `LogsPanel` ≤ ~240; `LogsTablePanel` ≤ ~265; `LogsFiltersPanel` ≤ ~120.
- [ ] `logs-ui.test.ts` covers filter + sort predicates; ordinal logic extracted to `logs-ordinal.ts` + tested.
- [ ] `npm run test:unit` includes the new logs tests and passes; `npm run check` clean.

---

## 5. memories (#9) — 🟡 split the panel, kill the last `:global`

**Files:** `admin_frontend/src/lib/features/memories/`. `MemoriesPage` (121) and
`MemoriesDialogs` (160) are fine; `memory-pure.ts` (409) is already well-tested
(`memory-pure.test.ts`, 351 lines) — **leave those**.

`MemoriesPanel.svelte` (408) is the problem:

1. Extract the sticky toolbar (6 filter controls + Clear/Refresh, ~113–199) into
   `MemoriesToolbar.svelte`.
2. Extract the **entities cell** (conditional relation-vs-summary markup, ~261–277) into
   `MemoriesEntitiesCell.svelte` — it's the densest per-row block.
3. **Remove the `:global` rule** in the scoped `<style>` (~404–407):
   `:global(.admin-table-shell-dense.memories-table-wrap) :global(table) { white-space: normal; min-width: 1180px; }`.
   It exists only because the table is nested below the scoped root. Wrap the
   `AdminTableShell` in a `<div class="memories-table-container">` and rewrite as a normal
   scoped rule (`.memories-table-container :global(table) { … }`).

**Target: `MemoriesPanel` ≤ ~280.**

**Green criteria**
- [ ] `MemoriesPanel.svelte` ≤ ~280; toolbar + entities-cell extracted.
- [ ] No `:global` block in the feature (the table rule is scoped via a container div).
- [ ] Filtering/sorting/dialogs behave identically; `npm run check` clean.

---

## 6. Test backlog — catalog (#8), image-lab (#12), dashboard (#11)

These three are **structurally fine** (thin shells, small files, good folders) but ship
**zero tests**. They flip to 🟢 by covering their pure/controller logic — no
decomposition needed.

- **catalog (#8)** — best targets, all currently untested:
  - `shared/catalog-pricing.ts` (143) — pricing math, highest value.
  - `shared/catalog-filter-ui.ts` (134) and `shared/catalog-sort.ts` (90) — filter/sort predicates.
  - Add `catalog-pricing.test.ts`, `catalog-filter-ui.test.ts`, `catalog-sort.test.ts`.
- **image-lab (#12)** — logic lives in `state/image-lab-controller.svelte.ts` (282). Extract
  any pure helpers (profile/recipe building, validation) into a `shared/*.ts` and test
  those; the controller's API orchestration can stay thin.
- **dashboard (#11)** — `shared/dashboard-gateway.ts` (39) and any derive logic in
  `state/dashboard-controller.svelte.ts` (90) are the pure bits to cover.

**Green criteria**
- [ ] catalog: pricing + filter + sort modules each have a `*.test.ts`.
- [ ] image-lab: pure helpers extracted from the controller and tested.
- [ ] dashboard: gateway/derive logic tested.
- [ ] `npm run test:unit` green.

---

## 7. What to leave alone

Do **not** refactor these for size — they are green and the largest files in them are
**tested**, so churn buys nothing:

- **server (#1)** — 47-line shell, tiny files. The model to copy.
- **eval (#2)** — 13 tests, clean `browse/answers/execute/report/view` slices.
  `EvalAnswersPane` (392) and `EvalExecutePane` (374) are large but well-tested; leave them.
- **preferences (#3)** — decomposed into ~20 `SectionCard`s already.
- **characters (#4)** — recently refactored into `browse/sections/modals/state/shared`;
  `CharacterResolvedBlock` (365) is tested.
- **metrics (#5), channels-devices (#6), chat-channels (#7)** — small, sliced, tested.

> Note: the three `border-destructive/50 … hover:bg-destructive/10` hits in
> `ChatMessageComposer`, `ChatMessagesToolbar`, and `StderrLogButton` are **destructive
> *button* styles**, not raw inline-alert blocks — they are a legitimate variant and are
> **not** a violation of the "use `InlineDestructiveAlert`" rule. No action.

---

## 8. Global definition of done

A feature is 🟢 when:
- No `.svelte` file materially over ~250 lines without a tested reason; page shells ≤ 200.
- No duplicated chrome/pickers/markdown pipelines; one shared component per repeated pattern.
- No new `:global` blocks in feature pages (scoped components or `app.css` only).
- Pure logic lives in `*.ts` and is unit-tested; controllers stay thin.
- `npm run check` and `npm run test:unit` both pass.
