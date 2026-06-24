# Admin UI — Shared Component Promotion Opportunities

**Status:** Findings / proposal (not yet executed)
**Scope:** `admin_frontend/src` — feature-local Svelte components that could be promoted into the shared layer.
**Goal:** Identify individual page/feature components that are either duplicated across features or already reused across features, and should live in the shared component layer instead of inside a single feature folder.

> Abiding by the repo's *no-backward-compatibility* rule: promotions below move/merge components outright (no wrappers, no shims kept for old import paths).

---

## Method

Two grounded signals were used — no name-guessing:

1. **Cross-feature imports** — a component defined under `lib/features/<A>/` but `import`ed by a different feature `<B>` is *proven* shared, just mislocated.
2. **Byte-level duplication** — the same widget reimplemented independently in ≥2 features (compared markup + scoped CSS).

Toolbar, filter-bar, badge, and detail-panel clusters were also inspected and **rejected** (already wrapping shared primitives or genuinely domain-specific) — see [Verified NOT worth promoting](#verified-not-worth-promoting).

---

## Existing shared layer (baseline)

The shared layer is already broad and healthy. Candidates below are what's *missing* from it.

| Area | Location | Examples |
| --- | --- | --- |
| UI primitives | `lib/components/ui/` | dialog, popover, command, input-group, markdown, badge, button, form-field, `OrderedModelPicker`, `multi-select-filter` |
| Page chrome | `lib/components/page/` | `AdminPageHeader`, tab strip, `SectionCard`/`SectionCardMuted`, `DetailPanelShell`, `StatTile`/`MetricCard`, `SectionScrollNav`, `table/*` |
| Inline feedback | `lib/ui/` | `InlineDestructiveAlert`, `InlineWarningAlert`, `InlineLoading`, `InlineEmptyState`, `ToastHost` |
| Cross-cutting | `lib/search/`, `lib/live/`, `lib/catalog/active-providers/` | `Highlight`, `SearchInput`, `LiveDegradedBanner`, active-providers panel/dialogs |

---

## Tier A — Promote now (duplication or proven cross-feature reuse)

### A1. `ClampText` — merge `EvalClampAnswer` + `ClampCell`
- **Sources:** `lib/features/eval/answers/EvalClampAnswer.svelte`, `lib/features/graph-runs/shared/ClampCell.svelte`
- **Evidence:** The `.clamp` / `.clamp--open` / `.clamp-toggle` scoped CSS is **byte-identical** in both; both use the same `ChevronUp/ChevronDown` more/less toggle wrapping `Highlight`. They differ only by `line-clamp` count (2 vs 3) and by eval's extra overflow-measurement + bulk expand/collapse hooks. Six files use `-webkit-line-clamp`.
- **Proposal:** One `lib/components/ui/ClampText.svelte` with a `lines` prop, optional real-overflow measurement (ResizeObserver), and optional bulk `open`/`tick` controls.
- **Impact:** High.

### A2. `ExpandCollapseButtons` — hoist to shared
- **Source:** `lib/features/graph-runs/shared/ExpandCollapseButtons.svelte`
- **Evidence:** Eval's `EvalAnswersPane.svelte` (~line 344, `expandAllFolds` / `collapseAllFolds`) hand-rolls the same expand-all/collapse-all button pair that graph-runs already extracted.
- **Proposal:** Move to `lib/components/page/` (or `ui/`); have eval consume it. Pairs naturally with A1.
- **Impact:** Medium-High.

### A3. `CollapsibleSectionCard` — generalize `KnowledgeCollapsibleSectionCard`
- **Source:** `lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte`
- **Evidence:** **Already cross-imported by `eval`.** The component is fully generic — title + chevron + `aria-controls`/`hidden` body (correct disclosure a11y) + `summary` / `collapsedSummary` / `headerActions` snippets. The only feature-flavored part is the `KNOWLEDGE_SECTION_CARD` / `KNOWLEDGE_SECTION_TITLE` token strings.
- **Proposal:** Promote to `lib/components/page/CollapsibleSectionCard.svelte`; pass the card/title class tokens as props (default to the blessed `SectionCard` tokens).
- **Impact:** High (proven reuse, currently mislocated under a feature).

### A4. `CopyButton` — extract the copy-with-feedback pattern
- **Sources:** `lib/features/server/shared/PublicKeyCopyField.svelte`, `lib/features/logs/LogsDetailPanel.svelte`, `lib/features/knowledge/ask/KnowledgeAskPanel.svelte`
- **Evidence:** Each hand-rolls a `Copy` → `Check` icon-swap button with its own `copied` flag + reset timer. `navigator.clipboard.writeText` appears in 6 modules.
- **Proposal:** One `lib/components/ui/CopyButton.svelte` that owns the copied state + auto-reset timer, plus an optional `CopyField` (readonly input + button) wrapper for the field case.
- **Impact:** Medium-High.

---

## Tier B — Relocate / de-feature-ize (cross-imported, more domain-flavored)

### B1. Move `GraphRangeSlider` → `lib/components/ui/RangeSlider.svelte`
- **Source:** `lib/features/knowledge/graph/GraphRangeSlider.svelte`
- **Evidence:** Its own header comment says *"Graph-local on purpose; not a shared control"* — but `eval` already imports it. It's a generic bits-ui two-knob range slider (controlled `[lo, hi]`, `format` label callback). The comment is **stale**.
- **Proposal:** Relocate to `lib/components/ui/`, drop the stale comment.
- **Impact:** Medium.

### B2. Watch the eval ↔ graph-runs trace coupling
- **Sources:** `lib/features/graph-runs/shared/TraceTabs.svelte`, `TraceDialogShell.svelte`, `GraphRunsIngestTraceDialog.svelte`, `GraphRunsRetrievalTraceDialog.svelte`
- **Evidence:** Densest cross-feature edge — `eval` imports 7+ symbols from `graph-runs`. These are trace-domain, not generic UI.
- **Proposal:** Leave `graph-runs` as owner for now. If a third consumer appears, hoist into a shared `lib/trace/` area.
- **Impact:** Medium-Low (watch, don't rush).

---

## Tier C — Generic but single-consumer today (hoist opportunistically)

Reusable in shape but only one caller each, so promoting now would be speculative — flag, don't rush:

| Component | Source feature | Generic form |
| --- | --- | --- |
| `ValidityPill` | graph-runs | colored ✓/✗ `StatusPill` (already de-duped from two trace dialogs internally) |
| `Sparkline` | metrics | generic mini-chart |
| `CreatableTagsSelect` / `CreatableCategorySelect` | knowledge | generic creatable combobox |
| `RefreshableSectionCard` | channels-devices | `SectionCard` + refresh affordance |

---

## Verified NOT worth promoting

Read and confirmed already-correct — do not chase these:

- **Filter bars** — `ModelsFilterBar`, `KnowledgeAskFilterBar`, `KnowledgeBrowseFilterBar` already wrap `AdminFilterBar`. `KnowledgeGraphFilterBar` is a domain faceted-dropdown widget.
- **Toolbars (×6)** — mostly domain-specific layouts. `MemoriesToolbar` already wraps `AdminPageStickyToolbar`. Only `CharacterEditToolbar` + `EvalCorpusReviewToolbar` share a thin sticky skeleton (marginal; an optional `AdminToolbar` wrapper has low payoff).
- **Badges** — `AutostartBadge` already wraps the shared `Badge`; `ProviderFreeOffersBadge` is a domain dialog.
- **Detail panels (×10)** — domain content; `DetailPanelShell` + `AdminMasterDetail` already supply the chrome.

---

## Suggested sequencing

1. **PR 1 (cleanest first):** A1 `ClampText` + A2 `ExpandCollapseButtons` together (eval + graph-runs are the shared callers).
2. **PR 2:** A3 `CollapsibleSectionCard` (move out of `knowledge/shared`, parameterize tokens, update eval + knowledge imports).
3. **PR 3:** A4 `CopyButton` (+ optional `CopyField`).
4. **PR 4:** B1 relocate `GraphRangeSlider`.
5. Defer Tier B2 and Tier C until a second/third consumer materializes.

Each PR should keep the app working, run `npm run check` and `npm run test:unit` in `admin_frontend/`, and verify the affected pages in the Vite dev site (`http://localhost:5173`).
