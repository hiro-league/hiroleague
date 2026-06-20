# Search & Filter Unification

> **Why this is first.** Search/filter is the **largest duplication surface** in the admin
> UI — bigger than any single feature. **13 free-text search sites** (only 3 use the global
> input) and **16 structured-filter sites** (several forking the table primitives), with the
> highlight algorithm written **4×** and the match predicate **~9×**. A small `lib/search/`
> layer plus a few filter-primitive upgrades collapse most of it.
>
> Direction + examples below; the matrices are the already-extracted evidence.

---

## A. Free-text search

### The duplication (verified)

| Thing | Count |
|---|---|
| Bespoke `<input>` search markup (not using global `AdminFilterBarSearch`) | **8** (only 3 use the global) |
| `toLowerCase().includes` match predicate | **~9 copies** |
| Segment-split highlighter (same `indexOf` loop → `{text,hit}[]`) | **4** |
| `<mark>` highlight styles | **4** |
| Hand-rolled clear-X button | **6** |
| Debounce timers | **3 different constants**; 10 sites have **none** |

The 4 highlighters: `splitHighlight` (`graph-runs/shared/retrieval-trace-derive.ts:128`),
`highlightSegments` (`eval/shared/eval-highlight.ts:10`), `highlightParts`
(`knowledge/graph/graph-detail-helpers.ts:13`), `highlightPreviewSegments`
(`graph-runs/graph-runs-pure.ts:204`). The 3 debounce owners: `logs-controller.svelte.ts:365`
(250ms), `knowledge-browse.svelte.ts:122` (300ms), `create-graph-search.svelte.ts:30`.

### Site matrix

| # | Site | Input | Debounce | Scope | Highlight | Sync |
|---|---|---|---|---|---|---|
| 1 | Eval answers `EvalAnswersPane.svelte:243` | bespoke | none | client | `EvalHighlight` | URL `ans_q` |
| 2 | Eval corpus review `EvalCorpusReviewToolbar.svelte:50` (also injected into the ingest trace dialog) | bespoke ×2 | none | client | `EvalHighlight` | ephemeral |
| 3 | Graph-runs runs `GraphRunsRunsPanel.svelte:134` | **global** | none | client | `highlightPreviewSegments` | ephemeral |
| 4 | Graph detail `KnowledgeGraphDetailPanel.svelte:310` | bespoke | none | client | `GraphDetailHighlight` | ephemeral |
| 5 | Memories `MemoriesToolbar.svelte:83` | **global** | none | client | none | URL `mem_q` |
| 6 | Logs `LogsToolbar.svelte:84` | bespoke | 250ms | **server** | none | session |
| 7 | Knowledge browse `KnowledgeBrowseFilterBar.svelte:36` | **global** | 300ms | **server** | none | ephemeral |
| 8 | Graph unified `KnowledgeGraphToolbar.svelte:111` | bespoke | `SEARCH_DEBOUNCE_MS` | **hybrid** (client + chunk server) | canvas ring | ephemeral |
| 9 | Retrieval trace `GraphRunsRetrievalTraceDialog.svelte:110` | bespoke | none | client | `HighlightText` | ephemeral |
| 10 | Ingest trace dialog | **no own search** — hosts #2 via snippet | — | — | — | — |
| 11–13 | Combobox typeaheads (`multi-select-filter:57`, `KnowledgeGraphFilterDropdown:151`, `CreatableTagsSelect:48`) | bits-ui internal | none | client | none | ephemeral |

### Proposed `lib/search/`

```ts
// lib/search/match.ts — kills ~9 predicate copies + 4 highlighters
matchesQuery(haystack: string, query: string): boolean;                 // toLowerCase().includes; blank => false
rowMatches<T>(row: T, query: string, fields: (r: T) => string[]): boolean;  // each site injects only its fields
splitOnQuery(text: string | null, query: string): { text: string; hit: boolean }[];
```

```svelte
<!-- lib/search/Highlight.svelte — one component, one .search-hit token -->
{#each splitOnQuery(text, query) as s, i (i)}{#if s.hit}<mark class="search-hit">{s.text}</mark>{:else}{s.text}{/if}{/each}
```

```ts
// lib/search/create-text-search.svelte.ts — query state + debounce + (optional) URL + server hook
createTextSearch(opts?: {
  debounceMs?: number;            // 0 = immediate (default)
  urlKey?: string;                // delegates to useTableFilters when set
  onCommit?: (q: string) => void; // fires after debounce — server-query sites (logs/browse/graph chunk); wraps one AbortController
}): { query: string; debounced: string; set(q: string): void; clear(): void; teardown(): void };
```

```svelte
<!-- lib/search/SearchInput.svelte — retires 6 bespoke inputs; folds in AdminFilterBarSearch -->
<!-- props: value, onValueChange, placeholder, count?, busy?, size? — Search icon + clear-X + optional N/… badge -->
```

### Adoption

- **Clean adopters** (client filter + segment highlight): #1, #2, #3, #4, #9 → all already render `{text,hit}` segments; the highlight swap is a pure rename/import.
- **Input + match + debounce only** (no DOM highlight): #5 (memories), #6 (logs, server via `onCommit`), #7 (browse, server).
- **Keep custom core:** #8 graph unified (hybrid client+server, abortable, **canvas** highlight not DOM) — reuse `createTextSearch` + `<SearchInput count busy>`, not `<Highlight>`. #11–13 comboboxes are bits-ui-internal — keep, but route their predicate through `matchesQuery`.

### Order of attack (suggestion, not binding)

1. `splitOnQuery` + `<Highlight>` — highest ROI, zero behavior change, deletes the most code.
2. `lib/search/match.ts` — point the ~9 predicate copies at it (each keeps only its field extractor).
3. `<SearchInput>` — retire the 6 bespoke inputs + clear buttons.
4. `createTextSearch` — standardize the 3 debounce constants; wire #6/#7/#8 server commits.

---

## B. Structured filter / facet / sort

Two house primitives exist and work: `AdminFilterBar` + `AdminFilterBarSelect` +
`useTableFilters` + `useTableSort` + `AdminTableHeaderCell` (single-select/table) and
`MultiSelectFilter` (multi-select). **Memories is the gold-standard adopter** (filters +
sort + URL all global). 16 sites total; the actionable drift:

| Drift | Where | Fix |
|---|---|---|
| Filter **state** hand-rolled as raw `$state` (no `useTableFilters`, no URL sync, duplicated clear/has logic, un-extracted predicate) | **graph-runs** (`graph-runs-controller.svelte.ts:74`, `:537`), **knowledge-browse** (`knowledge-browse.svelte.ts:41`, `:157`) | Adopt `useTableFilters({keys, urlSync:true})` → deep-linkable; extract `visibleRows`/predicate into a tested pure fn |
| 4 inline `<select>` + a **forked 3-state sort** (`useEvalAnswerSort` + `EvalAnswerTableHeaderCell`) | **eval answers** (`EvalAnswersPane.svelte:273`) | Add `threeState?: boolean` + a `'none'` direction to `useTableSort`/`AdminTableHeaderCell`; delete the fork |
| Private `FilterSelectWithClear` + fully bespoke session sort with hand-written aria | **logs** (`LogsFiltersPanel.svelte`, `logs-ui.ts:compareLogRows`) | Promote `FilterSelectWithClear` or add `clearable`/`onClear` to `AdminFilterBarSelect`; logs sort is a bigger lift (TanStack + level-priority) — lower priority |
| "select + label + clear-button" pattern | **~4 copies** | The promoted clearable select above |
| "distinct values + `(no X)` sentinel" facet-option builder | **3 copies** (`memory-pure.ts:277`, `graph-runs-controller.svelte.ts:104`, `EvalAnswersPane.svelte:118`) | Pure `distinctOptionsWithSentinel(rows, accessor, {emptyLabel})` |

### Proposed primitive upgrades

- `clearable` + `onClear` on `AdminFilterBarSelect` (or promote `logs/shared/FilterSelectWithClear` to `components/page/table/`).
- `threeState` mode + `'none'` direction on `useTableSort` + `AdminTableHeaderCell` (kills the eval fork).
- Pure `distinctOptionsWithSentinel` helper (kills 3 facet-option derivations).
- Adopt `useTableFilters` in graph-runs + knowledge-browse (free URL deep-linking; their predicates become tested pure fns).

### Keep bespoke (justified — do not merge)

- **Knowledge-graph node/edge facets** (`KnowledgeGraphFilterDropdown` + `graph-filter-pure.ts`) — color master-toggle, per-option weight, weight↔alpha sort over a force-graph. The component header documents *why* it's not `MultiSelectFilter`.
- **Graph-options range/structural filters** (`GraphOptionsFiltersSection`) — continuous sliders, not table semantics.
- **Trace-dialog stage toggles** (`createToggleSet`, `sortByStage`, `strikeDropped`) — pipeline disclosure, not table rows.
- **Eval corpus extraction range sliders**.
- **`CreatableCategorySelect` / `CreatableTagsSelect`** — create-on-type token inputs, a different control family.

---

## Top 2 wins

1. **Search:** one `splitOnQuery` + `<Highlight>` + `lib/search/match.ts` (deletes 4 highlighters + ~9 predicates with no behavior change).
2. **Filter:** adopt `useTableFilters` in graph-runs + knowledge-browse, and converge the eval/logs select+sort forks onto upgraded primitives.
