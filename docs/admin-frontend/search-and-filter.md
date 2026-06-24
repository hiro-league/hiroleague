# Search & Filter Unification

> **Why this is first.** Search/filter is the **largest duplication surface** in the admin
> UI — bigger than any single feature. Many free-text search sites (most still bespoke,
> not the shared input) and many structured-filter sites (several forking the table
> primitives), with the highlight algorithm written **4×** and the match predicate **many
> times over**. A small `lib/search/` layer plus a few filter-primitive upgrades collapse most of it.
>
> **This doc is a build spec, not a sketch.** It is written so a junior agent can execute it
> without guessing. The exact existing APIs you must build on are in
> [§0 Reference](#0-reference--existing-primitives-verbatim); a complete worked migration is in
> [§A.5 Worked slice](#a5-worked-slice-graph-detail-highlight--predicate-end-to-end). Where a
> choice is *not* yours to make, it is flagged in [§D Decisions for a human](#d-decisions-for-a-human).

---

## Scope refresh — audited 2026-06-24

This section records the delta between the first draft and the current code. **The audit
re-verified every site.** Line numbers below are current but **drift** — anchor on the
**symbol/component name**, treat the line as a hint.

| Change since first draft | Detail |
|---|---|
| **New search site** | `eval/answers/EvalRowDetailDialog.svelte` (~`:65`) — per-row search over recalled Facts/Entities/Episodes/Evidence. **In scope**, clean adopter. |
| **New filter sites — already gold-standard** | `catalog/browse/ModelsFilterBar.svelte` + `catalog/state/catalog-controller.svelte.ts` already use `useTableFilters` **and** `useTableSort`, both URL-synced. **Not a migration target — reference adopter.** Catalog is a **second gold standard** alongside Memories. |
| **New filter site — keep bespoke** | `knowledge/ask/KnowledgeAskFilterBar.svelte` — selects + `CreatableCategorySelect`/`CreatableTagsSelect`; **no free-text search**. Token-input family, **keep bespoke**. |
| **Eval already partly migrated** | `EvalAnswersPane.svelte` **already uses `useTableFilters`** (URL `ans_*`); filter keys are extracted to `eval/shared/eval-answer-filters.ts`. **Remaining eval work is ONLY the sort fork** (`useEvalAnswerSort`) — the filter-state migration the first draft asked for is **done**. |
| **Removed** | Standalone "ingest trace dialog" search (old #10) is gone — the ingest dialog hosts the corpus-review search snippet instead. |
| **Count corrections** | Highlighters: **4** (confirmed, unchanged). Bespoke search inputs: **8** (5 sites now use the global `AdminFilterBarSearch`, not 3). Hand-rolled clear-X: **7**. `FilterSelectWithClear` is used **3× inside logs only** (not spread across features). Sentinel/facet builders: **3** (1 extracted/tested, 2 still inline `$derived`). |
| **"Pure rename" caveat found** | `highlightPreviewSegments` (graph-runs #3) takes a **pre-lowercased, un-trimmed needle** (`previewSearchNeedle`), not the raw query. Its swap is **not** a pure rename — see [§A.5 gotchas](#gotchas-read-before-you-start). |

---

## 0. Reference — existing primitives (verbatim)

You are extending these. **Read them before writing `lib/search/`** — the new code must match
their shape (controllers expose reactive state via **getters**, `.svelte.ts`, no classes).

**`lib/components/page/table/use-table-filters.svelte.ts`** — URL/in-memory filter state:
```ts
function useTableFilters<TKey extends string>(opts: {
  keys: readonly TKey[];
  defaults?: Partial<Record<TKey, string>>;
  urlSync?: boolean;                       // syncs to ?key=... via replaceState + popstate
}): {
  readonly filters: Record<TKey, string>;  // GETTER — reactive
  set: (key: TKey, value: string) => void; // trims when urlSync
  reset: () => void;
};
```

**`lib/components/page/table/use-table-sort.svelte.ts`** — sort state (asc/desc only today):
```ts
type TableSortDirection = 'asc' | 'desc';   // NOTE: no 'none' yet — see §B
function useTableSort<TCol extends string>(opts: {
  defaultBy: TCol; defaultDirection?: TableSortDirection;
  allowed: readonly TCol[];
  urlSync?: boolean; sortParam?: string; directionParam?: string;
}): {
  readonly sortBy: TCol; readonly direction: TableSortDirection;  // GETTERS
  toggle: (c: TCol) => void;                 // delegates to cycleTableSort
  setSort: (c: TCol, d: TableSortDirection) => void;
  ariaSort: (c: TCol) => 'ascending' | 'descending' | 'none';
};
```
The cycle logic lives in `table-sort-utils.ts` → `cycleTableSort` (new col → `asc`; same col
toggles `asc`/`desc`). **This is the function the `threeState` upgrade in §B edits.**

**`lib/components/page/table/AdminFilterBarSearch.svelte`** — the global search input (today):
```ts
// props: { label?, value=$bindable(''), placeholder?, class?, inputClass?, onValueChange?(v) }
// renders: <FormField><input type="search" bind:value oninput={onValueChange}></FormField>
// NO clear-X, NO debounce, NO count/busy badge.  SearchInput in §A.3 supersedes it.
```

**`AdminFilterBarSelect.svelte`** — `{ label, value=$bindable, options, placeholder?, onValueChange? }`.
**No `clearable`** — that is the §B upgrade. **`AdminTableHeaderCell.svelte`** — `{ column, sort, sortable?, children }`, calls `sort.toggle(column)`.

**Reactivity contract for everything new in this doc:** controllers are plain functions in
`*.svelte.ts` returning an object whose reactive fields are **getters over `$state`** (copy the
shape of `useTableSort` above). A `.svelte` consumer then reads `ctrl.debounced` directly in markup
and it stays reactive. **Do not** return bare `$state` values or `{ value }` wrappers — that breaks
reactivity across the module boundary.

---

## A. Free-text search

### A.1 The duplication (verified 2026-06-24)

| Thing | Count | Notes |
|---|---|---|
| Bespoke search `<input>` (not `AdminFilterBarSearch`) | **8** | 5 sites now use the global input |
| `toLowerCase().includes` match predicate | **many**, mostly wrapped in per-file helpers (`hasMatch`, `rowHaystack`, …) | |
| Segment-split highlighter (`indexOf` loop → `{text,hit}[]`) | **4** | listed below |
| `<mark>` highlight styles | **4**, two color families (yellow `#facc15` vs amber) | see [§D-1](#d-decisions-for-a-human) |
| Hand-rolled clear-X button | **7** | |
| Debounce timers | **2 distinct constants** (250ms, 300ms) across 3 owners; most client sites have none | |

**The 4 highlighters** (all the same loop; 3 return `{text, hit}`, 1 returns `{text, match}`):

| Function | Path:line | Returns | Component wrapper |
|---|---|---|---|
| `splitHighlight` | `graph-runs/shared/retrieval-trace-derive.ts:128` | `{text, hit}` | `HighlightText.svelte` (owns `.search-hit`) |
| `highlightSegments` | `eval/shared/eval-highlight.ts:10` | `{text, hit}` | `EvalHighlight.svelte` (amber) |
| `highlightParts` | `knowledge/graph/graph-detail-helpers.ts:13` | **`{text, match}`** | `GraphDetailHighlight.svelte` (amber) |
| `highlightPreviewSegments` | `graph-runs/graph-runs-pure.ts:204` | `{text, hit}` | inline in `GraphRunsRunsPanel.svelte` — **takes pre-lowercased needle** |

**The 3 debounce owners:** `logs-controller.svelte.ts:365` (250ms), `knowledge-browse.svelte.ts:122`
(300ms), `create-graph-search.svelte.ts:30` (`SEARCH_DEBOUNCE_MS = 250`, from `graph-types.ts:47`).

### A.2 Site matrix (refreshed)

| # | Site (symbol @ file:line) | Input | Debounce | Scope | Highlight | URL sync |
|---|---|---|---|---|---|---|
| 1 | Eval answers `EvalAnswersPane.svelte:~260` | bespoke | none | client | `EvalHighlight` (via result/recalled tables) | `ans_q` |
| 2 | Eval corpus review `EvalCorpusReviewToolbar.svelte:~49` | bespoke | none | client | `EvalHighlight` | ephemeral |
| 3 | Graph-runs runs `GraphRunsRunsPanel.svelte:~134` | **global** | none | client | `highlightPreviewSegments` (inline) | ephemeral |
| 4 | Graph detail `KnowledgeGraphDetailPanel.svelte:~311` | bespoke (`type=search`) | none | client | `GraphDetailHighlight` | ephemeral |
| 5 | Memories `MemoriesToolbar.svelte:~83` | **global** | none | client | none | `mem_q` |
| 6 | Logs `LogsToolbar.svelte:~86` | bespoke | 250ms | **server** | none | session |
| 7 | Knowledge browse `KnowledgeBrowseFilterBar.svelte:~36` | **global** | 300ms | **server** | none | ephemeral |
| 8 | Graph unified `KnowledgeGraphToolbar.svelte:~111` | bespoke | `SEARCH_DEBOUNCE_MS` | **hybrid** (client + server chunk) | **canvas** ring (not DOM) | ephemeral |
| 9 | Retrieval trace `GraphRunsRetrievalTraceDialog.svelte:~114` | bespoke | none | client | `splitHighlight` / `HighlightText` | ephemeral |
| 10 | **Eval row detail `EvalRowDetailDialog.svelte:~65`** (NEW) | bespoke | none | client | `EvalHighlight` + table predicates | ephemeral |
| 11–13 | Combobox typeaheads (`multi-select-filter.svelte:~56`, `KnowledgeGraphFilterDropdown.svelte:~150`, `CreatableTagsSelect.svelte:~28`) | bits-ui internal | none | client | none | ephemeral |

*Catalog (`ModelsFilterBar`) and Knowledge-ask (`KnowledgeAskFilterBar`) have **no free-text
search** — they are filter-only, covered in §B.*

### A.3 Proposed `lib/search/`

```ts
// lib/search/match.ts — replaces the predicate copies + backs the 4 highlighters
export function matchesQuery(haystack: string, query: string): boolean;
// trim+lowercase both; blank query => false (matches existing hasMatch semantics)

export function rowMatches<T>(row: T, query: string, fields: (r: T) => string[]): boolean;
// true if ANY field matchesQuery; each site injects only its own field extractor

export function splitOnQuery(
  text: string | null | undefined,
  query: string
): { text: string; hit: boolean }[];
// EXACT port of splitHighlight: trims query internally, blank/empty => [{text, hit:false}].
// This is the single canonical loop the other 3 highlighters collapse into.
```

```svelte
<!-- lib/search/Highlight.svelte — generalizes the existing HighlightText.svelte -->
<script lang="ts">
  import { splitOnQuery } from './match';
  let { text, query }: { text: string | null | undefined; query: string } = $props();
</script>
{#each splitOnQuery(text, query) as s, i (i)}{#if s.hit}<mark class="search-hit">{s.text}</mark>{:else}{s.text}{/if}{/each}
<style>
  /* single home for the highlight token — see §D-1 for the color decision */
  .search-hit { background: color-mix(in srgb, #facc15 55%, transparent); color: inherit; border-radius: 2px; padding: 0 1px; }
</style>
```

```ts
// lib/search/create-text-search.svelte.ts — query state + debounce + optional URL + server hook
export function createTextSearch(opts?: {
  debounceMs?: number;              // 0 = immediate (default)
  urlKey?: string;                  // when set, delegates persistence to useTableFilters([urlKey])
  onCommit?: (q: string) => void;   // fires after debounce — server sites (#6/#7/#8); wrap ONE AbortController inside
}): {
  readonly query: string;           // GETTER — the live input value (every keystroke)
  readonly debounced: string;       // GETTER — settles after debounceMs; === query when debounceMs 0
  set(q: string): void;
  clear(): void;
  teardown(): void;                 // clears the pending timer; call from an $effect cleanup
};
// Reactivity: query/debounced are getters over $state (mirror useTableSort). A .svelte consumer
// reads `search.debounced` in markup and it updates reactively. See §0 contract.
```

```svelte
<!-- lib/search/SearchInput.svelte — retires the 7 bespoke inputs + clear buttons; supersedes AdminFilterBarSearch -->
<!-- props: value, onValueChange, placeholder?, count?, busy?, size?  → Search icon + clear-X + optional N/spinner badge -->
```

### A.4 Adoption plan (with done-criteria)

| Bucket | Sites | What changes | Done = |
|---|---|---|---|
| **Clean highlight swap** (already render `{text,hit}` segments) | #1, #2, #3, #4, #9, #10 | import `splitOnQuery`/`<Highlight>`; delete the 4 local highlighters + 3 wrapper components | the 4 highlighter fns + `EvalHighlight`/`GraphDetailHighlight`/`HighlightText` are deleted (folded into `Highlight.svelte`); `npm run test:unit` green; visual match per [§D-1](#d-decisions-for-a-human) |
| **Input + predicate + (debounce)** — no DOM highlight | #5 (memories), #6 (logs, server via `onCommit`), #7 (browse, server) | swap input → `<SearchInput>`; predicate → `matchesQuery`/`rowMatches`; #6/#7 wire `onCommit` | bespoke input + clear-X gone; server debounce still 250/300ms; abortion still works |
| **Keep custom core** | #8 graph unified | reuse `createTextSearch` + `<SearchInput count busy>` only; **keep the canvas-ring highlight** (not `<Highlight>`) and the hybrid abort | input/debounce shared; highlight untouched |
| **Comboboxes** | #11–13 | route only their internal predicate through `matchesQuery`; keep the bits-ui control | predicate centralized; control unchanged |

### A.5 Worked slice: graph-detail highlight + predicate, end-to-end

This is the **template** for the whole "clean highlight swap" bucket. Do this one first, exactly;
the other five sites are the same moves. It touches a highlighter that returns the **odd field
name** (`{text, match}`), so it also demonstrates the rename friction.

**Before** — `knowledge/graph/graph-detail-helpers.ts`:
```ts
export type TextPart = { text: string; match: boolean };
export function highlightParts(text: string, query: string): TextPart[] { /* indexOf loop */ }
export function hasMatch(text: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q ? text.toLowerCase().includes(q) : false;
}
```
…consumed by `GraphDetailHighlight.svelte` (`{#each highlightParts(text, query) as p}{#if p.match}<mark …>`),
and `hasMatch(c.title, search)` in the panel's filter predicate (~`:161`).

**Step 1 — `splitOnQuery` (port `splitHighlight` verbatim into `lib/search/match.ts`).**
Copy the loop from `retrieval-trace-derive.ts:128`. Add `lib/search/match.test.ts` covering:
blank query → one non-hit segment; multiple hits; case-insensitivity; `null`/`undefined` text.
**Done =** `npm run test:unit -- match` green.

**Step 2 — `Highlight.svelte`** (code in §A.3). It replaces `GraphDetailHighlight.svelte`.

**Step 3 — migrate the consumer.** In the panel: `import Highlight from '$lib/search/Highlight.svelte'`,
replace `<GraphDetailHighlight text={…} query={search}/>` with `<Highlight text={…} query={search}/>`.
The field rename (`match` → `hit`) is **absorbed by the component** — call sites don't see it.

**Step 4 — predicate.** Replace `hasMatch(c.title, search)` with `matchesQuery(c.title, search)`
(identical semantics — both trim+lowercase, blank → false). Delete `hasMatch` and `highlightParts`
and `GraphDetailHighlight.svelte`.

**Step 5 — verify.** `npm run check` (admin_frontend) + `npm run test:unit`. Then the preview
workflow: open the graph detail panel, type a query, confirm matches highlight and the row filter
still narrows. **Done =** checks green + highlight visually correct (see §D-1) + no dead imports.

#### Gotchas (read before you start)
- **`highlightPreviewSegments` (#3) is NOT a pure rename.** It takes a **pre-lowercased,
  un-trimmed needle** (`previewSearchNeedle`), whereas `splitOnQuery(text, query)` trims+lowercases
  the **raw query** internally. When you migrate #3, pass the **raw query** to `splitOnQuery` and
  delete the `previewSearchNeedle` pre-computation — don't pass the lowercased needle (double work,
  and trimming differs on whitespace-only queries). Update `graph-runs-pure.test.ts` accordingly.
- **Color unification is a visible change.** Today: graph-runs `.search-hit` is yellow `#facc15`;
  eval + graph-detail marks are amber. Folding all into one `.search-hit` token **changes those
  amber sites to yellow.** That is a real visual decision — see [§D-1](#d-decisions-for-a-human),
  don't pick silently.
- **`<mark>` only, never `{@html}`.** Every highlighter is deliberately injection-safe (data-bound
  text nodes). Keep it that way.

### A.6 Order of attack (free-text)

1. `splitOnQuery` + `<Highlight>` — **the §A.5 slice**, then repeat for #1, #2, #9, #10, and #3
   (mind the needle gotcha). Highest ROI, deletes the most code.
2. `match.ts` predicates — point the per-file helpers (`hasMatch`, `rowHaystack`, combobox
   `.includes`) at `matchesQuery`/`rowMatches`.
3. `<SearchInput>` — retire the 7 bespoke inputs + clear buttons (#5/#6/#7 first; #8 input only).
4. `createTextSearch` — standardize debounce; wire #6/#7/#8 server commits + abort.

---

## B. Structured filter / facet / sort

House primitives (§0) work. **Two gold-standard adopters now exist: Memories and Catalog**
(both: filters + sort + URL via the house hooks). The actionable drift:

| Drift | Where (symbol @ file:line) | Fix | Done = |
|---|---|---|---|
| Filter **state** hand-rolled as raw `$state` (no `useTableFilters`, no URL sync, un-extracted predicate) | **graph-runs** (`graph-runs-controller.svelte.ts:~118`), **knowledge-browse** (`knowledge-browse.svelte.ts:~41`) | adopt `useTableFilters({keys, urlSync:true})`; extract `visibleRows`/predicate into a tested pure fn | deep-linkable filters; predicate has a `*.test.ts`; behavior unchanged |
| **Forked 3-state sort** (`useEvalAnswerSort` + `EvalAnswerTableHeaderCell`) | **eval answers** (`EvalAnswersPane.svelte:~290`) | add `threeState?: boolean` + a `'none'` direction to `cycleTableSort`/`useTableSort`/`AdminTableHeaderCell`; delete the fork | eval uses house sort; **Memories + Catalog sort still pass** (regression guard); fork files deleted |
| Private `FilterSelectWithClear` (used 3× in logs) + bespoke session sort w/ hand-written aria | **logs** (`LogsFiltersPanel.svelte`, `logs-ui.ts:compareLogRows`) | add `clearable`/`onClear` to `AdminFilterBarSelect` (or promote `FilterSelectWithClear` to `components/page/table/`); **logs sort stays** (TanStack + level-priority — bigger lift, lower priority) | logs selects use the house primitive; sort untouched |
| "distinct values + `(no X)` sentinel" facet builder | **3 copies**: `memory-pure.ts:~277` (extracted ✓), `graph-runs-controller.svelte.ts:~147` (inline `$derived`), `EvalAnswersPane.svelte:~135` (inline, no sentinel) | pure `distinctOptionsWithSentinel(rows, accessor, {emptyLabel})` in `components/page/table/`; point all 3 at it | one tested helper; 2 inline derivations deleted |

### B.1 Proposed primitive upgrades (signatures)

```ts
// table-sort-utils.ts — extend the cycle to optionally pass through 'none'
type TableSortDirection = 'asc' | 'desc' | 'none';   // 'none' added
function cycleTableSort(active, dir, column, opts?: { threeState?: boolean }): {...};
// threeState: new col → asc; same col cycles asc → desc → none → asc
// useTableSort gains `threeState?: boolean`; AdminTableHeaderCell renders no arrow when 'none'.
// REGRESSION RISK: Memories + Catalog use the 2-state path — they must NOT pass threeState and
// must keep cycling asc/desc only. Guard with table-sort-utils.test.ts cases for BOTH modes.

// AdminFilterBarSelect.svelte — add:  clearable?: boolean;  onClear?: () => void;
//   renders an X when clearable && value !== '' ; onClear ?? (() => onValueChange?.(''))

// components/page/table/distinct-options.ts
function distinctOptionsWithSentinel<T>(
  rows: readonly T[],
  accessor: (r: T) => string | undefined,
  opts?: { emptyLabel?: string; emptyValue?: string }   // defaults: '(no value)', '__empty__'
): { value: string; label: string }[];   // sorted; sentinel first when any row is empty
```

Then **adopt `useTableFilters` in graph-runs + knowledge-browse** (free URL deep-linking; their
predicates become tested pure fns). **Do not touch Memories or Catalog** — they are the reference.

### B.2 Keep bespoke (justified — do NOT merge)

All still present and still justified (re-verified 2026-06-24):
- **Knowledge-graph node/edge facets** (`KnowledgeGraphFilterDropdown` + `graph-filter-pure.ts`) — color master-toggle, per-option weight, weight↔alpha sort over a force-graph. Header documents *why*.
- **Graph edge/view filters** (`create-graph-edge-filters.svelte.ts`, `create-graph-view-filters.svelte.ts`) — date-range + `Set`-based visibility toggles, not table semantics.
- **Graph-options range/structural filters** (`GraphOptionsFiltersSection`) — continuous sliders.
- **Trace-dialog stage toggles** (`createToggleSet`, `sortByStage`, `strikeDropped`) — pipeline disclosure.
- **Eval corpus extraction range sliders** (`EvalCorpusExtractionFilters`).
- **`CreatableCategorySelect` / `CreatableTagsSelect`** (and the whole `KnowledgeAskFilterBar`) — create-on-type token inputs, a different control family.

---

## C. Order across the whole effort

1. **A.5 worked slice** (graph-detail) → prove `splitOnQuery` + `<Highlight>`, then sweep the other 5 highlight sites.
2. **`match.ts` predicates** → centralize the `.includes` copies.
3. **`SearchInput` + `createTextSearch`** → retire bespoke inputs, standardize debounce, wire server commits.
4. **Filter primitives** → `distinctOptionsWithSentinel`, then `useTableFilters` adoption (graph-runs, knowledge-browse), then the `threeState`/`clearable` upgrades + eval-sort de-fork.

Run after each step (admin_frontend): `npm run check` and `npm run test:unit`. Add/adjust unit
tests for any pure fn you create or move (`match`, `distinct-options`, the migrated predicates,
`table-sort-utils` both modes).

---

## D. Decisions for a human

These are **not** the implementing agent's to make — confirm with the maintainer first.

1. **Highlight color.** Unify every site on the yellow `.search-hit` token (changes eval +
   graph-detail from amber → yellow), **or** keep per-family color via a `tone`/`class` prop on
   `<Highlight>`? *Recommended: unify* (consistency, one token) — but it is a visible change, so
   confirm.
2. **`AdminFilterBarSelect.clearable` vs promote `FilterSelectWithClear`.** Add the prop to the
   house select, or move logs' component into `components/page/table/`? *Recommended: add the prop*
   (one primitive) — but check no caller depends on `FilterSelectWithClear`'s exact markup.
3. **Logs sort.** Left as bespoke (TanStack + level-priority) for now — confirm it stays out of
   scope rather than being forced onto `useTableSort`.

---

## TL;DR

- **Audit done (2026-06-24):** doc refreshed against current code. Net new: **EvalRowDetailDialog**
  search (in scope), **Catalog** as a 2nd gold-standard adopter (reference, not a target), eval's
  filter-state migration **already done** (only the **sort fork** remains), Knowledge-ask stays
  bespoke. Counts corrected (8 bespoke inputs, 5 global, 7 clear-X, 4 highlighters).
- **Now junior-executable:** added **§0 verbatim primitive signatures**, the **reactivity
  contract** (getters over `$state`), a **fully worked slice** (graph-detail, 5 steps + verify),
  **per-bucket done-criteria + test targets**, and three **gotchas** (the `highlightPreviewSegments`
  needle, color unification, no-`{@html}`).
- **Decisions flagged for a human** (§D): highlight color unification, select-clearable approach,
  logs-sort scope — the agent must **ask, not guess**.
- **Order:** worked slice → sweep highlighters → predicates → `SearchInput`/`createTextSearch` →
  filter primitives (`distinctOptionsWithSentinel`, `useTableFilters` adoption, `threeState`/
  `clearable`, eval-sort de-fork). `npm run check` + `npm run test:unit` after each.
