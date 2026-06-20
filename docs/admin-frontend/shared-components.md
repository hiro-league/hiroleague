# Shared Components — Promote & Keep-Local

> Components living in feature folders that are **duplicated across ≥2 features** → promote
> to the global library. Equally important: a **"keep local"** list, so future work doesn't
> over-abstract unrelated things into one bad component.
>
> Global homes: `components/page/`, `components/ui/`, `ui/`, `styling/`, `format/`, new `state/`.

---

## Promote

| Candidate | Evidence | Target / verdict |
|---|---|---|
| **HighlightText** | Same algorithm written 2× — `eval/shared/eval-highlight.ts:10` + `EvalHighlight.svelte` vs `graph-runs/shared/retrieval-trace-derive.ts:128` + `HighlightText.svelte` (also `graph-detail-helpers.ts:13`, `graph-runs-pure.ts:204`) | Owned by [search-and-filter.md](search-and-filter.md) → `lib/search/` (`splitOnQuery` + one `<Highlight>` + one `.search-hit`) |
| **use-clipboard / CopyButton** | Copy + "copied" timer reimplemented 4× — `workspace-store.svelte.ts:322`, `eval-traces.svelte.ts:160`, `LogsDetailPanel.svelte:29`, `PublicKeyCopyField.svelte` (one gives no feedback) | `state/use-clipboard.svelte.ts` returning `{ copied, copy(text) }` (+ optional `ui/CopyButton`). Domain copy-text formatters stay local. |
| **KnowledgeCollapsibleSectionCard → SectionCardMuted** | Near-verbatim fork of the global `SectionCardMuted` — the chevron-button class string is **byte-identical** (`SectionCardMuted.svelte:77` ≡ `KnowledgeCollapsibleSectionCard.svelte:39`); global already does collapsible + registry | **Feature-reimplements-global** — rebuild on `SectionCardMuted` (pass a `headerActions`/summary snippet + a class override prop). The missing collapse-all registry is a feature, not a reason to fork. |
| **DetailPanelShell + DetailFieldGrid** | The "aside + bordered header + close + scroll body" + labeled KV grid is hand-rolled 3× — `GraphRunsNodeDetailPanel.svelte:62`, `LogsDetailPanel.svelte:44`, `KnowledgeGraphDetailPanel.svelte:295` (~150 dup lines) | `components/page/DetailPanelShell.svelte` (`title`, `onClose`, `headerActions` snippet, body) + `DetailFieldGrid`. Mirrors the `TraceDialogShell` win. |
| **StatTile / KpiCard** | `DashboardPanel.svelte` inlines 3 KPI cards; `GraphRunsRunAggregateMetrics` has its own; `metrics/MetricCard` already exists but isn't shared | Promote `metrics/MetricCard` to `components/page/`; refactor DashboardPanel onto it (drops ~120 lines). |
| **ClampCell, ExpandCollapseButtons** (secondary) | `graph-runs/shared/ClampCell.svelte` (line-clamp + more/less) is generic once `HighlightText` is global; eval uses bare `line-clamp-2`. `ExpandCollapseButtons` is a 36-line generic pair, single consumer today | Promote to `components/ui/` when a 2nd consumer appears; low urgency. |

## Adherence stragglers (small)

- ~9 hand-rolled empty-state blocks bypass `InlineEmptyState` (3 in `KnowledgeAskPanel.svelte` — `:172`,`:179`,`:231`); retire the bespoke `MutedStatusLine`.
- 3 destructive-outline buttons (`StderrLogButton.svelte:25`, `ChatMessageComposer.svelte:136`, `ChatMessagesToolbar.svelte:79`) repeat `border-destructive/50 … hover:bg-destructive/10` — add a `destructive-outline` button variant instead. (These are *button* styles, **not** inline-alert violations — see refactor-plan §7.)

---

## Deliberately keep local (do **not** merge)

These look mergeable but aren't — forcing one abstraction would be worse than the duplication:

- **Status icons / pills / badges** — `LogLevelIcon`, `LogSourceIcon`, `ValidityPill`, `AutostartBadge`, `ProviderFreeOffersBadge` are **5 unrelated domain lookups** over different value spaces, not one `{icon,color,label}` pattern. `AutostartBadge` already delegates to the global `Badge`. Keep.
- **Creatable selects** — `CreatableTagsSelect` (chip-input writer) and `CreatableCategorySelect` (create-on-type) share zero logic with the filter `multi-select-filter` (a checklist). Keep.
- **Trace primitives** — `graph-runs/shared/*` (`StageCard`, `TraceTable`, `TraceTabs`, `TraceAnswers`, `FlowNav`) are **never deep-imported** by other features (verified); eval/knowledge consume them only via the public trace-dialog components. Textbook feature-owns-implementation. Keep.
- **`*-a11y.ts` / `*-page-lifecycle.ts` / `*-table-ui.ts` / `*-format.ts`** — naming conventions, not hidden abstractions. Each is feature-specific id maps / class constants / domain formatters. The one truly generic formatter (`compact-datetime.ts`) is **already global**. Keep.

> Rule of thumb for new work: promote only when the *logic* is identical (highlight, clipboard
> timer) or one file is a **fork** of an existing global (the collapsible card). Structural
> resemblance over different domains is not a reason to merge.
