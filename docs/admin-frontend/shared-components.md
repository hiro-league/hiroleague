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
| **ConfirmDialog** | Same confirm shape hand-rolled ~10× across **6 features** — `Dialog.Root` + title + warning body + `Cancel`/`variant="destructive"` footer + a `pending` flag disabling both buttons: `EvalClearResultsConfirmDialog`/`EvalRebuildConfirmDialog`/`EvalSwitchCorpusConfirmDialog.svelte`, `ChatChannelDeleteModal`/`ChatChannelClearMessagesModal.svelte`, `DeviceRevokeDialog.svelte`, `server/dialogs/GatewayRemoveDialog`/`GatewayStopDialog`/`WorkspaceRemoveDialog.svelte`, `knowledge/browse/KnowledgeBrowseDeleteDialog`/`KnowledgeBrowseRemoveGraphDialog.svelte` (≈130–160 dup lines; verified by grep — 13 `variant="destructive"` dialogs, minus the genuine large content dialogs like `EvalRowDetailDialog`) | `ui/dialog/ConfirmDialog.svelte` (`title`, `message?`, `confirmLabel`, `destructive?`, `pending`, `onConfirm`, `onOpenChange`) wrapping the shadcn `dialog/*` primitives. Mirrors the `TraceDialogShell` win. Large content/form dialogs (`KnowledgeDocumentReingestDialog`, `ChatChannelEditorModal`, `EvalRowDetailDialog`, …) stay local. |
| **HighlightText** | Same algorithm written **4×** — `eval/shared/eval-highlight.ts:10` (`highlightSegments`) + `EvalHighlight.svelte`; `graph-runs/shared/retrieval-trace-derive.ts:128` (`splitHighlight`) + `HighlightText.svelte`; `graph-detail-helpers.ts:13` (`highlightParts`); `graph-runs-pure.ts:204` (`highlightPreviewSegments`). No global helper exists. | Owned by [search-and-filter.md](search-and-filter.md) → `lib/search/` (`splitOnQuery` + one `<Highlight>` + one `.search-hit`) |
| **use-clipboard / CopyButton** | Copy + "copied" timer reimplemented **3×** — `workspace-store.svelte.ts:322`, `eval-traces.svelte.ts:153`, `LogsDetailPanel.svelte:29` (this one gives **no** "copied" feedback). `PublicKeyCopyField.svelte` is **not** a 4th impl — it's presentational and already reuses `workspace-store.copyText()` (the model to copy). | `state/use-clipboard.svelte.ts` returning `{ copied, copy(text) }` (+ optional `ui/CopyButton`). Domain copy-text formatters stay local. |
| **KnowledgeCollapsibleSectionCard → SectionCardMuted** | Near-verbatim fork of the global `SectionCardMuted` — the chevron-button class string is **byte-identical** (`SectionCardMuted.svelte:77` ≡ `KnowledgeCollapsibleSectionCard.svelte:39`); global already does collapsible + registry. **Now a second fork exists**: `characters/sections/CharacterSectionCard.svelte` (kept local — see below) plus the inline knowledge-ingest section cards — three feature variants and counting. | **Feature-reimplements-global** — rebuild on `SectionCardMuted` (pass a `headerActions`/summary snippet + a **class/style-override prop**). The override prop is what lets the character/knowledge variants stop forking; the missing collapse-all registry is a feature, not a reason to fork. |
| **DetailPanelShell + DetailFieldGrid** | The "aside + bordered header + close + scroll body" + labeled KV grid is hand-rolled 3× — `GraphRunsNodeDetailPanel.svelte:62`, `LogsDetailPanel.svelte:44`, `KnowledgeGraphDetailPanel.svelte:295` (~150 dup lines) | `components/page/DetailPanelShell.svelte` (`title`, `onClose`, `headerActions` snippet, body) + `DetailFieldGrid`. Same *extract-the-shell* pattern as `TraceDialogShell` (note: `TraceDialogShell` is a shadcn modal `Dialog`, not an aside — analogous refactor, not the same structure). |
| **StatTile / KpiCard** | `DashboardPanel.svelte` inlines 3 KPI cards; `GraphRunsRunAggregateMetrics` has its own; `metrics/MetricCard` already exists but isn't shared | Promote `metrics/MetricCard` to `components/page/`; refactor DashboardPanel onto it (drops ~120 lines). |
| **ClampCell, ExpandCollapseButtons** (secondary) | `graph-runs/shared/ClampCell.svelte` (line-clamp + more/less) is generic once `HighlightText` is global; eval uses bare `line-clamp-2`. `ExpandCollapseButtons` is a 36-line generic pair, single consumer today | Promote to `components/ui/` when a 2nd consumer appears; low urgency. |
| **AdminIconToggleGroup** (secondary) | Labeled, `aria-pressed` icon-toggle button group hand-rolled 3× in `catalog/browse/ModelsFilterBar.svelte` (Kind/Hosting/Online) + 1× in `logs/LogsToolbar.svelte` (log level) — 2 features, ~125 lines. `AdminFilterBar` is a container, not this control. | `components/page/AdminIconToggleGroup.svelte` (`label`, `labelId`, `options:{value,label,Icon}[]`, `selected`, `onSelectedChange`, `multiSelect?`). Low urgency — only 2 features today. |

## Adherence stragglers (small)

- ~9 hand-rolled empty-state blocks bypass `InlineEmptyState` (3 in `KnowledgeAskPanel.svelte` — `:172`,`:179`,`:231`); retire the bespoke `MutedStatusLine`.
- 3 destructive-outline buttons (`StderrLogButton.svelte:25`, `ChatMessageComposer.svelte:136`, `ChatMessagesToolbar.svelte:79` — last one is `border-destructive/60`) repeat `border-destructive/5x … hover:bg-destructive/10` — add a `destructive-outline` button variant instead. (These are *button* styles, **not** inline-alert violations — see refactor-plan §7.)

## Logic-level candidate (needs a design call, not a mechanical extract)

- **use-async-resource** — `loading` + `error` + `data` + `try/catch/finally` + `refresh` is repeated across **8+ `*-controller.svelte.ts`** (catalog, channels, devices, characters, chat-channels, dashboard, memories, logs) — ~200 lines, ~12 call sites. A `state/use-async-resource.svelte.ts` returning `{ data, loading, error, refresh }` would collapse it. **Not a drop-in:** these controllers are Svelte-5 classes with `$state` fields, so the composable has to graft onto class instances cleanly — decide the shape before extracting. Lower priority than the component promotes above.

---

## Deliberately keep local (do **not** merge)

These look mergeable but aren't — forcing one abstraction would be worse than the duplication:

- **Status icons / pills / badges** — `LogLevelIcon`, `LogSourceIcon`, `ValidityPill`, `AutostartBadge`, `ProviderFreeOffersBadge` are **5 unrelated domain lookups** over different value spaces, not one `{icon,color,label}` pattern. `AutostartBadge` already delegates to the global `Badge`. Keep.
- **Creatable selects** — `CreatableTagsSelect` (chip-input writer) and `CreatableCategorySelect` (create-on-type) share zero logic with the filter `multi-select-filter` (a checklist). Keep.
- **CharacterSectionCard** — looks like a third `SectionCardMuted` fork but **isn't a promote**: its class string is *deliberately* different (`rounded-xl`, `color-mix` borders, custom padding/shadow), it's **not collapsible**, and it's used 6× **within one feature**. Structural resemblance over a single domain ≠ merge. It does, however, justify giving the global `SectionCardMuted` a **class-override prop** (see the Promote row) so it — and the knowledge forks — can converge later. Keep local for now.
- **RefreshableSectionCard** (`channels-devices/shared/`) — wraps the global `SectionCard` and adds refresh + inline loading/error/empty states via the global `Inline*` components. It's a domain wrapper, not a card fork. Keep.
- **Trace primitives** — `graph-runs/shared/*` (`StageCard`, `TraceTable`, `TraceTabs`, `TraceAnswers`, `FlowNav`) are **never deep-imported** by other features (verified); eval/knowledge consume them only via the public trace-dialog components. Textbook feature-owns-implementation. Keep.
- **`*-a11y.ts` / `*-page-lifecycle.ts` / `*-table-ui.ts` / `*-format.ts`** — naming conventions, not hidden abstractions. Each is feature-specific id maps / class constants / domain formatters. The one truly generic formatter (`compact-datetime.ts`) is **already global**. Keep.

> Rule of thumb for new work: promote only when the *logic* is identical (highlight, clipboard
> timer) or one file is a **fork** of an existing global (the collapsible card). Structural
> resemblance over different domains is not a reason to merge.

---

## Implementation notes

> For the **actionable** rows above. `HighlightText` is owned by [search-and-filter.md](search-and-filter.md) and `use-async-resource` is design-gated — **don't start either from this doc**.

### Build order

1. **`ConfirmDialog`** — no dependencies, ~10 consumers, highest payoff. Do it first.
2. **`StatTile/MetricCard`**, **`AdminIconToggleGroup`**, the **`destructive-outline`** button variant, the **empty-state** cleanups — all independent; any order.
3. **`DetailPanelShell + DetailFieldGrid`** — trickiest (divergent bodies); do it after you're comfortable with the snippet pattern from `ConfirmDialog`.
4. **`ClampCell`** is blocked on `HighlightText` going global (lands via `search-and-filter.md`) — defer.

### Verify after each promote

From `admin_frontend/`: run `npm run check` (svelte-check + types) and `npm run test:unit`. For visual rows (cards, dialogs, panels) eyeball on the **Vite dev site at `http://localhost:5173`** (not the served `:18083`). **One promote per commit** so a regression is bisectable — don't batch them.

### ConfirmDialog — the consumers vary on 4 axes; absorb all four or migration silently changes behavior

Reading the ~10 confirm dialogs, the differences are real, not cosmetic — two embed extra controls and one confirm isn't destructive:

| Axis | Variants seen in the wild | Component contract |
|---|---|---|
| **Open state** | `bind:open` (`$bindable`) — `EvalClearResultsConfirmDialog`, `KnowledgeBrowseDeleteDialog` · `open` + `onOpenChange` — `ChatChannelClearMessagesModal`, `EvalSwitchCorpusConfirmDialog` · `open={expr}` + close-on-false `onOpenChange` — `ChatChannelDeleteModal` (`target!==null`), `DeviceRevokeDialog` (`ctrl.revokeTarget!==null`), `GatewayRemoveDialog`/`WorkspaceRemoveDialog` (`store.dialog==='remove'`) | `open: boolean` + `onOpenChange?: (next:boolean)=>void`. Migrate `bind:open` callers to `open`+`onOpenChange`. |
| **Pending flag** | `busy` (chat; device `ctrl.busy`; gateway/workspace `store.busy`) · `deleting` (knowledge) · **none** (`EvalClearResults`, `EvalSwitchCorpus`) | `pending?: boolean` (default `false`) → `disabled` on the confirm button (and cancel where the original disabled it). |
| **Confirm style** | `variant="destructive"` (most) · **default** variant — `EvalSwitchCorpusConfirmDialog` ("Switch corpus") is **not** destructive | `destructive?: boolean` (default `true`). Don't blanket-apply destructive. |
| **Body** | bare `<p>` — chat delete/clear, device · `Dialog.Description` — eval, gateway/workspace path · **extra controls** — Gateway/Workspace purge **checkbox**, Knowledge **affected-docs list** | `message?: string` for the simple case **plus a `children` snippet** for the 3 that embed controls. A `message`-only API would drop the purge checkbox and the doc list — **don't ship without the snippet.** |

Passthrough props: `widthClass?` (default `sm:max-w-md`; consumers use `-lg`, `-xl`, and the `KNOWLEDGE_BROWSE_BULK_DIALOG` token) and `showCloseButton?` (Knowledge hides it while deleting). `confirmLabel` is a plain string (Knowledge computes it by count — fine).

**Status: implemented** at `components/ui/dialog/ConfirmDialog.svelte` (exported from `dialog/index.ts`); 11 consumers migrated; `npm run check` clean. Shipped API:

```ts
ConfirmDialog props: {
  open: boolean; onOpenChange?: (next: boolean) => void;
  title: string;
  message?: string;                            // plain text → auto-wrapped in <Dialog.Description>
  description?: Snippet;                        // rich a11y description — snippet must include its own <Dialog.Description>
  confirmLabel: string; cancelLabel?: string;  // cancel default "Cancel"
  destructive?: boolean;                       // default true → confirm variant 'destructive', else 'default'
  pending?: boolean;                           // default false → disables confirm
  disableCancelWhenPending?: boolean;          // default false → also disables cancel while pending
  widthClass?: string; showCloseButton?: boolean;
  onConfirm: () => void | Promise<void>;
  children?: Snippet;                          // body BELOW the header — embedded checkbox / list / <p>
}
```

Body precedence: `message` wins over `description` (mutually exclusive in the header); `children` always renders below the header. Use `message`/`description` for descriptive text (keeps `aria-describedby`), `children` for interactive controls (checkbox, affected-docs list).

Per-consumer migration: replace the `<Dialog.*>` block with `<ConfirmDialog .../>`; move `<p>`/`Description` text to `message` (or the `description` snippet when it has markup); move checkboxes/lists into the `children` snippet; set `disableCancelWhenPending` only for the dialogs whose original disabled Cancel during the in-flight op; map open/pending/variant per the table. **Leave untouched** the large content/form dialogs — `KnowledgeDocumentReingestDialog`, `KnowledgeDocumentMetadataDialog`, `KnowledgeDocumentChunksDialog`, `ChatChannelEditorModal`, `EvalRowDetailDialog`, `WorkspacePublicKeyDialog`, `*PairingDialog`, `CharacterPhotoCropModal`, the `*Create`/`*Edit` server dialogs.

### DetailPanelShell — keep each body as a snippet; don't unify the bodies

The 3 panels share only the **frame** (aside + bordered header + close + scrollable body). Their bodies are genuinely different — `GraphRunsNodeDetailPanel` uses a `dl`/`dt`/`dd` grid, `LogsDetailPanel` hand-rolled `div`s, `KnowledgeGraphDetailPanel` a tabbed switcher. So `DetailPanelShell` owns **only the frame** and takes the body as a `children` snippet. `DetailFieldGrid` is a **separate, optional** helper for the two KV-grid bodies only — Knowledge's tabbed body keeps its own markup. Forcing one unified body is the failure mode here.
