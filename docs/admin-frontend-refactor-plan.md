# Admin Frontend Refactor — Shared Layer & Per-Page Best Practices

**Status:** plan / not yet implemented
**Scope:** `admin_frontend/` (SvelteKit static app served by `hirocli`)
**Reference skill:** `.cursor/skills/svelte-best-practice/SKILL.md`
**Mode:** initial development — **no backward compatibility, no migration shims, no wrappers** (per `no-backward-compatibility.mdc`).

---

## 1. Why this refactor

Best-practices have been applied **per-page**, not as a shared layer. The result is that some pages (Characters, Knowledge, Logs, Graph runs, Chat channels) follow the SKILL.md target architecture (thin shell + `*.svelte.ts` controller + `*-classes.ts` tokens + small focused components), while others (Preferences, Catalog, Active providers, Metrics, Server tabs, Channels-devices, Dashboard) remain monolithic.

Even the refactored pages re-implement the same primitives independently:

- 10 pages each define their own `notify(kind, message)` + `toast` `$state` + `setTimeout` clearing.
- 2 unsaved-change guards exist (`navigation/unsaved-guard.svelte.ts` and `characters/characters-unsaved-guard.svelte.ts`) that differ only in one predicate.
- The same kicker / `brand-text-gradient` title / `inline-flex rounded-lg border bg-card p-1` tab strip is hand-copied on 8+ pages.
- One page (`PreferencesPage`) is `mx-auto … max-w-7xl` centered; every other page is `max-w-[1420px]` left-aligned.
- 3 features each load active providers and build chat/stt/tts/embedding `Set`s separately.
- Catalog reload (`reloadModelCatalog` + parallel re-fetch + notify) lives inline in 3 places.
- Inputs styled `h-10 rounded-md border border-input bg-background px-3 …` appear 50+ times as raw soup; the `FormField` and `$lib/components/ui/input` primitives are barely used outside of Characters.
- Loading / empty / destructive-error inline blocks repeat in 15+ places; `InlineDestructiveAlert` exists in `chat-channels/shared/` but is not promoted to the shared layer.
- Tables across Catalog, Active providers, Server, Channels-devices, Chat channels, Graph runs, Knowledge each re-implement column-header sort toggles, filter bars, master-detail layout, and refresh buttons with subtly different styling and state shape.
- Header-styling tokens (`KNOWLEDGE_HEADER_KICKER`/`_TITLE`/`_INTRO`, `GRAPH_RUNS_HEADER_KICKER`/`_TITLE`/`_INTRO`, `character-section-classes.ts`) exist as parallel feature-local copies of the same Tailwind strings.

The two largest pages — `PreferencesPage.svelte` (1163 lines) and `CatalogPage.svelte` (1031 lines) — concentrate most of these violations.

**Goal:** Promote the patterns the refactored features already use into a single **shared layer**, then bring every remaining page in line, eliminating per-page divergence.

---

## 2. Current-state digest

### 2.1 Page-level scorecard

| Page | LOC (Page.svelte) | Shape | Controller | Prefs module | Notes |
|---|---|---|---|---|---|
| Characters | 296 | thin shell + 21 files | yes | yes | reference exemplar; owns its own `unsaved-guard` copy |
| Graph runs | 113 | thin shell + 17 files | yes | partial | some `:global` table CSS; no toasts |
| Logs | 223 | split + 15 files | yes | feature-local | local `notify`; small `:global` for scroll lock |
| Chat channels | 181 | split + 28 files | yes | feature-local | toast in controller; `InlineDestructiveAlert` lives here |
| Knowledge | 89 | thin shell + 25 files | yes | feature-local | **styling exemplar** (`knowledge-ui.ts`) |
| **Preferences** | **1163** | **monolith** | **none** | **none** | scroll-spy nav + JSON dirty diff + 24 inline inputs + 7× `SingleModelPicker` |
| **Catalog** | **1031** | **monolith** | **none** | yes | dead third tab branch (L913+); pricing & filter UI inline |
| Active providers | 290 | monolith | none | none | ~90% overlap with Catalog dead branch |
| Channels-devices | 69 | thin shell | tabs use API directly | yes | hand-copied tab strip; local `notify` |
| Metrics | 391 | monolith | none | none | inline polling; `:global(.metric-card …)` |
| Server | 65 | thin shell | stores | yes | hand-copied tab strip; local `notify` |
| Dashboard | 228 | monolith | none | none | duplicates parts of server / catalog data fetch |

### 2.2 Top-right tabs — the most visible inconsistency

> ⚠ **Scope:** this section is about the **page-level top-right header area only** — the tab strip + action buttons that sit beside the page title. **Inner / in-page navigation** (Preferences' scroll-spy section nav with `#hash` anchors; Graph runs' underline subtab strip with dynamic per-record tabs) is a different pattern and is covered separately in §2.3. Do not unify them into one API.

The page-level top-right area appears in **six variants** today, and the same tab strip markup (`inline-flex rounded-lg border bg-card p-1`) is hand-copied on every page that uses one:

| Variant | Pages |
|---|---|
| **1. Tabs only** | Server, Channels-devices, Catalog |
| **2. Tabs + actions (buttons)** | Characters (tabs + `New character`); Chat channels |
| **3. Actions only (no tabs)** | Preferences (`Active providers` link + conditional `Reset`/`Save`); Active providers (`Add`/`Refresh`); Metrics (`Refresh`); Dashboard |
| **4. Dynamic "open record" chip** | Characters Detail chip (icon + truncated record name + X) — created on the fly when a list row is opened |
| **5. Link-style action (anchor to another page or to a tab on another page)** | Preferences' `Active providers` → `/active-providers/`; AdminShell global shortcut → `/chats/?tab=messages` |
| **6. No header** | rare; single-purpose pages with nothing top-right |

The underlying URL-sync logic is also duplicated on **two axes**: the markup itself, and the `*-preferences.svelte.ts` modules behind it. Today:

| Page | Has tab strip? | URL sync (`?tab=`) | Tab-pref storage | Lives in `lib/preferences/`? |
|---|---|---|---|---|
| Characters | yes | yes (+ `mode`, `character_id`) | session | yes |
| Catalog | yes | yes (+ filter params) | session | yes |
| Server | yes | yes | session | yes |
| Channels-devices | yes | yes | session | yes |
| Chat channels | yes | yes (+ `channel_id`) | session | **no — `chat-channels-nav.ts` (hand-rolled)** |
| Knowledge | yes | yes | session | **no — feature-local** |
| **Logs** | yes | **no** | sessionStorage only | **no — feature-local** |
| Graph runs | mostly tab-less | n/a (uses `?run=` deep link) | localStorage flags | n/a |
| **Preferences** | **section-nav, not tabs** | **`#hash`** | none | n/a |
| Metrics / Active providers / Dashboard | no tabs | n/a | n/a | n/a |

The four `lib/preferences/*-preferences.svelte.ts` files (catalog, server, channels-devices, plus the chat-channels variant) are **the same ~30-line file copy-pasted** with only the tab-id string literals different. That is the cleanest extraction in the whole refactor.

**Two divergences to flatten:**

- **Logs** has tabs but no `?tab=` — bookmarks / shared links don't restore the active tab.
- **Chat channels / Knowledge / Logs** put their tab logic outside `lib/preferences/`, so the home of "page tab state" is unpredictable.

**Special variant worth naming:** Characters' Detail tab is an *"open record" chip* (icon + truncated record label + X to close) rather than a fixed-label tab. The shared component must support this — it's the same pattern (opening a row from a list into a detail tab), and other pages will likely want it (Catalog → open provider, Knowledge → open document).

**Link-style actions (variant 5) must be real `<a href>`** — not buttons with `onclick={() => goto(...)}` — so middle-click / Cmd-click / "copy link" / right-click work. Preferences currently uses a `<Button onclick={goto}>` for the `Active providers` shortcut; that needs to become an anchor in the new shared API.

### 2.3 Inner / in-page navigation — explicitly NOT the same pattern

These look "tab-ish" but are **not** page-level tabs. Each has its own component, state model, and URL contract. The shared `AdminTabStrip` / `createTabPreferences` API does not cover them.

| Pattern | Used by | Visual | State | URL contract |
|---|---|---|---|---|
| **Section scroll-spy nav** | Preferences (`#preferences-models`, `…-media`, `…-memory`, `…-knowledge`, `…-tuning-profiles`) | sticky horizontal pill row, active = section currently under the marker line | `activeSectionId` from scroll observation + hash deep-link on mount | `#hash` (not `?tab=`) |
| **Underline subtab strip with dynamic per-record tabs** | Graph runs (`Graph runs (list)` + dynamically opened run inspectors, each with X) | underline, not pill; lives below the primary tab strip | `activePane: RUNS_TAB \| MEMORIES_TAB \| <runId>` + `openRunIds[]` | feature-owned (e.g. `?run=<id>`) |
| **Detail-panel inner tabs** | Possibly Logs detail / Knowledge document detail | feature-specific | feature-owned | feature-owned |

In the target architecture:

- Preferences' nav becomes a **`SectionScrollNav.svelte`** (page-local at first, promoted to `lib/components/page/` only when a second consumer appears — YAGNI).
- Graph runs' subtab strip stays feature-local (it's coupled to `openRunIds` state); we lift it to shared only if another page needs the same dynamic-record-tab pattern. The "open record chip" idea is shared via `AdminRecordTabChip`, but the *strip mechanics* are not generalised yet.

### 2.4 Page-level layout, dense headers, tables, and design tokens

Four more cross-cutting concerns surface from the survey:

#### 2.4.1 Page wrapper alignment / max-width

| Page | Wrapper |
|---|---|
| Characters / Graph runs / Catalog / Active providers / Channels-devices / Knowledge / Chat channels / Metrics / Server / Logs | `<section class="grid max-w-[1420px] gap-5">` (left-aligned) |
| **Preferences** | `<div class="mx-auto grid w-full max-w-7xl gap-5">` (**centered**, ≈1280 px) |

**Decision: standardise on left-aligned `max-w-[1420px]`.** Encode as `ADMIN_PAGE_MAX_W` in `admin-tokens.ts` and apply via the page wrapper component (the new `<AdminPageHeader>` owns the wrapping `<section>`, or equivalently a tiny `<AdminPageShell>` if header is not always present). Preferences becomes left-aligned during Phase 4 — no exceptions.

#### 2.4.2 Logs-style dense headers

Most pages fit the simple "kicker + title + tabs/actions" mould. **Logs is intentionally denser:**

- inline icon-button glued next to the title (open logs folder),
- a *live status line* under the title (`X visible / Y loaded · Searching… / Filtered`) — not the static "intro" text other pages use,
- a multi-row action bar (search input, sort toggle, pause, clear filters, auto-scroll, last-session, time-range select, divider, destructive clear-logs, detail-panel toggle),
- a chevron toggle that **collapses the secondary filters region** (`aria-expanded` / `aria-controls` to a `role="region"`).

**Decision: one component, snippet-rich.** `<AdminPageHeader>` exposes the following snippet slots so Logs can fit without a parallel component:

| Slot | Purpose | Used by |
|---|---|---|
| `kicker` (string prop) | small uppercase label | every page |
| `title` (string prop) | gradient page title | every page |
| `titleAdornment` (snippet) | inline icon-button next to the title | Logs |
| `subtitle` (string prop **or** snippet) | static intro text or a live status line | Logs (snippet) / others (string) |
| `tabs` (snippet) | renders an `<AdminTabStrip>` | tabbed pages |
| `actions` (snippet) | trailing buttons / link actions | most pages |
| `actionsCollapse` (snippet **or** props `{ expanded, onToggle, ariaControls }`) | optional chevron toggle that collapses a secondary region; wires `aria-expanded` / `aria-controls` automatically | Logs |

Default snippets cover the simple cases; pages that need none of the optional slots stay as concise as today's refactored features.

#### 2.4.3 Tables — sort, filters, master-detail, refresh

Tables are scattered across many pages with the same chrome but bespoke columns:

| Page | Sortable cols | Filter bar | Detail panel | Refresh |
|---|---|---|---|---|
| Catalog (providers / models) | yes | yes (multi-select) | no | yes |
| Active providers | partial | no | no | yes |
| Server (workspaces / gateways) | basic | no | inline status | yes |
| Channels-devices | basic | no | edit modal | yes |
| Chat channels (browse) | yes | search | no | yes |
| Graph runs (runs ledger) | yes | yes | yes — opens as a record tab | yes |
| Knowledge (browse) | yes | yes (search/category/tags) | yes (chunks, file preview) | yes |
| Logs | n/a (virtualized log feed) | yes (very dense) | yes (right-side detail) | n/a |

The **chrome** is highly repeatable; the **rows** are not (cells are bespoke per page). We therefore ship **composition primitives**, not a monolithic table component:

- `AdminTableShell.svelte` — outer `rounded-md border bg-card overflow-hidden` + sticky head row.
- `AdminTableHeaderCell.svelte` — sortable column header (click → cycle direction, `aria-sort`, indicator icon).
- `AdminFilterBar.svelte` — labelled select / search input row (consistent dropdown styling).
- `AdminMasterDetail.svelte` — split layout (list left, detail panel right, with toggle that closes the panel — same pattern Logs already uses for its detail-panel toggle).
- `useTableSort.svelte.ts` — `{ sortBy, direction, toggle(col), urlSync? }`.
- `useTableFilters.svelte.ts` — generic `{ filters, set(key, value), reset(), urlSync? }`.

Each page keeps full control of cell rendering; chrome and behaviour are uniform; URL sync of filters/sort comes for free. **Logs is exempt** — its virtualized feed is its own component.

#### 2.4.4 Header / section / form / table design tokens

The visible look is already fairly consistent (kicker + `brand-text-gradient` title + muted intro), but the Tailwind classes that produce it are duplicated as parallel constant sets (`KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, `character-section-classes.ts`) plus raw soup elsewhere. **Decision: consolidate into one `lib/styling/admin-tokens.ts`**; feature-local files become 5-line re-exports or are deleted.

Two distinct section-card recipes survive — they are real visual variants, not duplicates: `ADMIN_SECTION_CARD` (solid `bg-card`, used to group page-level sections) and `ADMIN_SECTION_CARD_MUTED` (translucent `bg-background/45`, used for nested cards inside another card). **Decision: keep both.**

#### 2.4.5 Sticky page headers (single- and two-level)

Today's sticky behaviour is inconsistent:

- **Knowledge** uses `KNOWLEDGE_PAGE_STICKY_HEADER = 'sticky top-16 z-10 …'` — title + tabs + filters all stick under the shell header.
- **Preferences** sticks **only** the section-nav at `top-16` and **lets the page title scroll away**. Once you've scrolled past the title there's no way to see "where am I" or get back to the top without manual scroll.
- **Logs** doesn't stick anything; it has a controls-collapse chevron instead.
- **Every other page** has nothing sticky — title and tabs scroll away.

Two real shapes are needed:

| Shape | What sticks | Pages |
|---|---|---|
| **Single-level sticky** | `kicker + title + tabs + actions` as one bar at `top-16` | Catalog/Providers, Channels-devices, Server, Active providers, Characters browse, Knowledge browse |
| **Two-level sticky** | Level 1 = title + tabs + actions at `top-16`; Level 2 = filter bar and/or table head at `top: 64px + level-1 height` | Catalog/Models, Knowledge browse with filters, Preferences (level 2 = section-nav), possibly Graph runs runs ledger |

**Decision: contract via prop + CSS-var spine (Option SA + backToTop).**

`<AdminPageHeader sticky>` measures itself with `ResizeObserver` and sets `--admin-page-header-h` on the wrapping element. A sibling `<AdminPageStickyToolbar>` sticks at `top: calc(theme(spacing.16) + var(--admin-page-header-h))`. Multi-level alignment "just works" without per-page magic numbers. When sticky and scrolled past a threshold, `AdminPageHeader` auto-renders a small ghost `backToTop` button in its action row (overridable via a `backToTop` snippet slot).

**Preferences specifically** stops hiding its header: in Phase 4 it becomes two-level sticky (header sticks; section-nav sticks below it). Header no longer scrolls away.

**Logs is exempt** — sticky-page-header doesn't fit the virtualized-feed-plus-dense-toolbar shape. It stays case-by-case.

#### 2.4.6 Panel portability — pages that should be mountable as tabs elsewhere

You should be able to take a page that currently has no tabs (Active providers, Metrics, Dashboard) or has a single tab, and **mount it as a tab inside another page** without rewriting it. Today this is structurally easy for some features (Server, Channels-devices already split into tab panels) and impossible for others (Active providers, Metrics, Dashboard own their entire page).

**Decision: enforce a five-rule "panel" contract** so any panel can be mounted as either a route's primary content or as a tab pane on another page:

1. Tab content is a `*Panel.svelte`, not a `*Page.svelte`. Panels never own page-level chrome (no `<svelte:head>`, no `<AdminPageHeader>`, no max-width wrapper).
2. State lives in a `*-store.svelte.ts` or `*-controller.svelte.ts` accepted as a prop, never constructed unconditionally inside the panel. The host (page or tab) passes one in.
3. Panels make no assumptions about `?tab=` or top-level URL params. URL params they need either come in as props or are namespaced (e.g. `?ap_provider=` instead of `?provider=`) when shared with a host.
4. Panels render a self-contained section (its own section-header, optional toolbar, body) — never the page-level kicker/title/tabs.
5. Loading / error / empty / toast use the shared primitives, with the toast notifier received as a prop or context (the host owns it).

`AdminTabStrip` learns about this directly: each tab descriptor declares a `kind`:

- `kind: 'pane'` — a local pane; the host renders the corresponding panel inline when active.
- `kind: 'route'` — an anchor that navigates elsewhere; renders as `<a href>` so middle-click / copy-link work. Same primitive as `AdminPageLinkAction`.

After the decomposition phases, the following become naturally portable:

- `ActiveProvidersPanel` (Phase 3) — already designed to be mountable from `/active-providers/` or as a Catalog tab.
- `MetricsPanel` (Phase 6) — could later become a tab in Server or a future Observability page.
- `WorkspacesPanel` / `GatewaysPanel` (Phase 6, Server tabs) — already structurally panels.
- `KnowledgeBrowsePanel` / `KnowledgeAskPanel` / `KnowledgeIngestPanel` — already three sibling panels; portable by accident, now by contract.

**Out of scope for portability:** Logs (its layout is route-shaped), Chat channels messages (audio coordinator + SSE assumptions), Characters edit (form + photo crop + unsaved guard are coupled to the page).

### 2.5 Top duplication offenders (ordered by leverage)

1. **Active-providers CRUD + table UI** — ~250–290 lines duplicated between `ActiveProvidersPage.svelte` and a **dead** `{:else}` branch in `CatalogPage.svelte`.
2. **Per-page `notify()` + `toast` + `setTimeout`** — 10 implementations, identical shape, varying timeout (3600 / 4500 ms).
3. **`PreferencesPage.svelte`** — 1163-line monolith; everything inline.
4. **`CatalogPage.svelte`** — 1031-line monolith; pricing/filter helpers inline.
5. **Duplicate unsaved guards** — `characters-unsaved-guard.svelte.ts` is line-for-line `unsaved-guard.svelte.ts` with one predicate rename.
6. **Page header + tab strip + tab URL-sync** — same kicker + `brand-text-gradient` + tablist on 8+ pages; four near-identical `*-preferences.svelte.ts` for tab URL sync; only Knowledge/Graph runs have extracted style constants.
7. **Table chrome** — sort headers, filter bars, master-detail toggles, refresh buttons hand-rolled per page.
8. **Loading / error / empty inline blocks** — same Tailwind strings in 15+ places.
9. **Catalog reload orchestration** — duplicated in Preferences (L501–527), Catalog (L347–362), Characters controller (L133–151).
10. **Form-control styling soup** — 20+ raw `<input>`/`<select>` in Preferences; parallel `KNOWLEDGE_INPUT_*` tokens; `FormField` and `$lib/components/ui/input` underused.
11. **Header / section design tokens** — `KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, `character-section-classes.ts` are parallel copies of the same Tailwind strings.
12. **Modal vs Dialog** — legacy `Modal.svelte` dominates (15+ usages); shadcn `Dialog` only in Knowledge.

---

## 3. Target architecture — the shared layer

A single home, with conventions. New additions land here unless feature-local is justified.

```text
admin_frontend/src/lib/
  shell/                       # AdminShell, sidebar nav (existing)
  navigation/                  # unsaved-guard (single canonical copy)
  preferences/                 # tab + URL prefs modules (one per page)
  api/                         # typed clients (existing)

  ui/                          # (rename target: `feedback/` once ToastHost moves)
    ToastHost.svelte                 (existing, presentational)
    Modal.svelte                     (legacy; phase-4 review)
    InlineDestructiveAlert.svelte    (move from chat-channels/shared)
    InlineLoading.svelte             (NEW)
    InlineEmptyState.svelte          (NEW)
    create-toast-notifier.svelte.ts  (NEW – replaces 10× notify)

  components/
    ui/                        # primitives — button, badge, dialog, popover, …
      input/  textarea/  form-field.svelte
    page/                      # NEW — admin page chrome
      AdminPageHeader.svelte         # kicker + title + titleAdornment + subtitle (str|snippet)
                                     #  + tabs + actions + actionsCollapse + backToTop snippets;
                                     #  owns the page wrapper (max-w-[1420px] left-aligned);
                                     #  optional sticky={true} prop publishes
                                     #  --admin-page-header-h via ResizeObserver.
      AdminPageStickyToolbar.svelte  # sticky second-level bar (filter bar / table head)
                                     #  — sticks at calc(top-16 + var(--admin-page-header-h)).
      AdminTabStrip.svelte           # generic tab strip; tab descriptors carry kind:
                                     #  'pane' (local content) or 'route' (anchor link).
      AdminTabButton.svelte
      AdminRecordTabChip.svelte      # icon + truncated label + X (Characters Detail tab)
      AdminPageLinkAction.svelte     # anchor-based action button (real <a href>)
      SectionCard.svelte             # ADMIN_SECTION_CARD (solid bg-card) variant
      SectionCardMuted.svelte        # ADMIN_SECTION_CARD_MUTED (translucent) variant
      SectionScrollNav.svelte        # inner #hash scroll-spy nav (Preferences-style)
    table/                     # NEW — table chrome primitives (composition, not monolith)
      AdminTableShell.svelte
      AdminTableHeaderCell.svelte    # sortable column header (aria-sort, indicator)
      AdminFilterBar.svelte
      AdminMasterDetail.svelte       # list-left / detail-right split + collapse toggle
      use-table-sort.svelte.ts       # { sortBy, direction, toggle(col), urlSync? }
      use-table-filters.svelte.ts    # { filters, set, reset, urlSync? }

  catalog/                     # cross-feature catalog domain
    catalog-picker-utils.ts          (existing)
    catalog-reload.ts                (NEW – the parallel-fetch+notify recipe)
    include-unknown-model.ts         (NEW – moved from PreferencesPage)
    active-providers/                (NEW – panel + store + dialogs)
      ActiveProvidersPanel.svelte
      active-providers-store.svelte.ts
      active-providers-add-dialog.svelte
      active-providers-scan-dialog.svelte

  styling/
    admin-tokens.ts            # NEW – shared Tailwind class constants
                                #   ADMIN_PAGE_MAX_W
                                #   ADMIN_HEADER_KICKER / _TITLE / _INTRO
                                #   ADMIN_PAGE_STICKY_HEADER
                                #   ADMIN_TABLIST_SHELL
                                #   ADMIN_SECTION_CARD       (solid bg-card)
                                #   ADMIN_SECTION_CARD_MUTED (translucent)
                                #   ADMIN_SECTION_TITLE / _HEADING_LG
                                #   ADMIN_FIELD_LABEL / _LABEL_TEXT
                                #   ADMIN_INPUT / _INPUT_LG / _SELECT / _SELECT_LG
                                #   ADMIN_TABLE / _TABLE_HEAD / _TABLE_ROW
                                #   cnAdminTab(active) / cnAdminTableRow(selected)
                                #   — supersedes the per-feature `*-classes.ts` files
                                #   for cross-cutting tokens; feature-local tokens
                                #   stay where they are.

  features/<area>/             # vertical slices (existing pattern)
    <Area>Page.svelte
    browse/  view/  edit/
    state/    # *.svelte.ts controllers, guards
    shared/   # feature-only helpers, *-classes.ts when truly local
```

### 3.1 Shared API contracts (target)

**Toast notifier** (replaces 10 copies):

```ts
// $lib/ui/create-toast-notifier.svelte.ts
export function createToastNotifier(timeoutMs = 4500) {
  let toast = $state<ToastMessage>(null);
  let handle = 0;
  function notify(kind: ToastKind, message: string) { /* … */ }
  function clear() { /* … */ }
  return { get toast() { return toast }, notify, clear };
}
```

Each page does:

```svelte
const toasts = createToastNotifier();
…
<ToastHost toast={toasts.toast} />
```

**Unsaved guard** — one canonical `createUnsavedGuard(getDirty, getActive, setDirty)`; delete the Characters copy.

**Page header — covers all 6 top-right variants and the dense Logs case:**

```svelte
<!-- Variant 1: tabs only -->
<AdminPageHeader kicker="Operations" title="Server">
  {#snippet tabs()}
    <AdminTabStrip ariaLabel="Server sections" tabs={[
      { id: 'workspaces', label: 'Workspaces' },
      { id: 'gateways',   label: 'Gateways' }
    ]} bind:active={prefs.activeTab} />
  {/snippet}
</AdminPageHeader>

<!-- Variant 2: tabs + actions (buttons + link) -->
<AdminPageHeader kicker="Configuration" title="Characters">
  {#snippet tabs()}
    <AdminTabStrip ariaLabel="Characters sections" tabs={fixedTabs} bind:active={prefs.activeTab}>
      <!-- Variant 4: dynamic "open record" chip slot -->
      {#snippet recordTab()}
        {#if prefs.activeTab === 'detail'}
          <AdminRecordTabChip icon={UserRound} label={detailLabel} onClose={openBrowse} />
        {/if}
      {/snippet}
    </AdminTabStrip>
  {/snippet}
  {#snippet actions()}
    <Button onclick={openNewCharacter}><Plus size={16} /> New character</Button>
  {/snippet}
</AdminPageHeader>

<!-- Variant 3: actions only, no tabs -->
<AdminPageHeader kicker="Workspace" title="Preferences">
  {#snippet actions()}
    <!-- Variant 5: link-style action — real <a href>, not a button -->
    <AdminPageLinkAction href={`${base}/active-providers/`} icon={KeyRound}>
      Active providers
    </AdminPageLinkAction>
    {#if dirty}
      <Button variant="outline" onclick={resetDraft}><RotateCcw size={16} /> Reset</Button>
      <Button onclick={savePrefs}><Save size={16} /> Save</Button>
    {/if}
  {/snippet}
</AdminPageHeader>

<!-- Logs: dense header — uses titleAdornment + subtitle snippet + actionsCollapse -->
<AdminPageHeader kicker="Operations" title="Logs">
  {#snippet titleAdornment()}
    <button type="button" class="…" onclick={openLogsFolder} title="Open logs folder">
      <FolderOpen size={13} />
    </button>
  {/snippet}
  {#snippet subtitle()}
    <p class="…">
      {visibleCount} visible / {loadedCount} loaded
      {#if searchBusy}<span class="ml-2 text-primary">Searching…</span>
      {:else if filtered}<span class="ml-2 text-primary">Filtered</span>{/if}
    </p>
  {/snippet}
  {#snippet actions()}
    <SearchInput …/>
    <Button …>Pause</Button>
    …
  {/snippet}
  {#snippet actionsCollapse({ expanded, toggle, ariaControls })}
    <Button variant="outline" size="icon" class="size-8"
      aria-expanded={expanded} aria-controls={ariaControls}
      aria-label={expanded ? 'Collapse log controls' : 'Expand log controls'}
      onclick={toggle}>
      {#if expanded}<ChevronUp size={16} />{:else}<ChevronDown size={16} />{/if}
    </Button>
  {/snippet}
</AdminPageHeader>
```

The `actionsCollapse` slot is **wired to a region elsewhere on the page** via `aria-controls={LOGS_FILTERS_REGION_ID}`. Per SKILL.md §10, that region must stay mounted (`hidden` toggle, not `{#if}`) so the relationship survives.

**Inner section nav (Preferences-style, NOT a page-level tab strip):**

```svelte
<SectionScrollNav
  ariaLabel="Preference sections"
  sections={[
    { id: 'preferences-models',    label: 'Models' },
    { id: 'preferences-media',     label: 'Media' },
    { id: 'preferences-memory',    label: 'Agent Memory' },
    { id: 'preferences-knowledge', label: 'Knowledge' },
    { id: 'preferences-tuning-profiles', label: 'Tuning profiles' }
  ]}
  scrollMarkerPx={128}
/>
<!-- consumer pages render their <section id="…"> children below -->
```

State lives in scroll position + `window.location.hash`. **No `?tab=` involvement.**

**Tab preferences (URL + session)** — one factory replaces four near-identical files:

```ts
// $lib/preferences/create-tab-preferences.svelte.ts
export function createTabPreferences<TTab extends string>(opts: {
  storageKey: string;                      // PREF_KEYS.<page>ActiveTab
  defaultTab: TTab;
  allowed: readonly TTab[];                // for normalizeTab()
  /** Extra ?params owned by this page; cleared on tab switch unless preserved. */
  urlParamsToReset?: readonly string[];
}) {
  let activeTab = $state<TTab>(opts.defaultTab);
  function initialize() { /* read ?tab= → session → default */ }
  async function setActiveTab(tab: TTab, extras: Record<string, string> = {}) {
    /* write session, replaceState ?tab= + extras */
  }
  return { get activeTab() { return activeTab }, initialize, setActiveTab };
}
```

Every tabbed page (including **Logs**, **Knowledge**, **Chat channels**) uses this factory. The four duplicate `*-preferences.svelte.ts` files collapse to one-liners that just supply config.

**Active providers** — one panel, one store; both `/active-providers/` and the Catalog providers tab mount the same panel.

**Catalog reload** — one `reloadCatalogAndRefetch({ kinds, onSuccess, onError })` function used by Preferences, Catalog, and the Characters controller.

**Inline feedback** — `InlineDestructiveAlert`, `InlineLoading`, `InlineEmptyState` are the only blessed shapes for those three states; raw inline markup is forbidden in PRs after Phase 1.

**Table primitives (composition, not monolith):**

```svelte
<AdminFilterBar>
  <AdminFilterBar.Search bind:value={filters.q} placeholder="Search models…" />
  <AdminFilterBar.Select label="Provider" bind:value={filters.providerId}
    options={providerOptions} />
  <AdminFilterBar.Select label="Kind" bind:value={filters.kind}
    options={kindOptions} />
</AdminFilterBar>

<AdminTableShell>
  <thead>
    <tr>
      <AdminTableHeaderCell column="display_name" sort={sort}>Model</AdminTableHeaderCell>
      <AdminTableHeaderCell column="provider_id"  sort={sort}>Provider</AdminTableHeaderCell>
      …
    </tr>
  </thead>
  <tbody>
    {#each rows as row (row.id)}
      <tr class={cnAdminTableRow(row.id === selectedId)} onclick={() => select(row)}>…</tr>
    {/each}
  </tbody>
</AdminTableShell>
```

```ts
const sort    = useTableSort({ defaultBy: 'display_name', urlSync: true });
const filters = useTableFilters({ keys: ['q', 'providerId', 'kind'], urlSync: true });
```

For master-detail layouts (Logs, Knowledge, Graph runs):

```svelte
<AdminMasterDetail bind:detailOpen={prefs.detailPanelOpen}>
  {#snippet list()}<…list/table…>{/snippet}
  {#snippet detail()}<…detail panel…>{/snippet}
</AdminMasterDetail>
```

The detail-panel toggle in the page header (`actionsCollapse` is for filters, but the same pattern is used here) wires to the same `bind:detailOpen` flag.

**Tokens** — `admin-tokens.ts` exports `ADMIN_PAGE_MAX_W`, `ADMIN_HEADER_KICKER` / `_TITLE` / `_INTRO`, `ADMIN_TABLIST_SHELL`, `ADMIN_SECTION_CARD` (solid) and `ADMIN_SECTION_CARD_MUTED` (translucent — kept as a deliberate variant), `ADMIN_SECTION_TITLE` / `_HEADING_LG`, `ADMIN_FIELD_LABEL` / `_LABEL_TEXT`, `ADMIN_INPUT` / `_INPUT_LG` / `_SELECT` / `_SELECT_LG`, `ADMIN_TABLE` / `_TABLE_HEAD` / `_TABLE_ROW`, plus helpers `cnAdminTab(active)` and `cnAdminTableRow(selected)`. Knowledge/Graph runs/Characters delete or re-export their feature-local copies (`KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, `character-section-classes.ts`).

**Sticky page headers (single- and two-level):**

```svelte
<!-- Single-level: header sticks; body scrolls -->
<AdminPageHeader sticky kicker="Configuration" title="Catalog">
  {#snippet tabs()}<AdminTabStrip … />{/snippet}
  {#snippet actions()}<Button onclick={refresh}>Refresh</Button>{/snippet}
</AdminPageHeader>

<!-- Two-level: header sticks; filter bar + table head stick below it -->
<AdminPageHeader sticky kicker="Catalog" title="Models">
  {#snippet tabs()}<AdminTabStrip … />{/snippet}
</AdminPageHeader>
<AdminPageStickyToolbar>
  <AdminFilterBar>…</AdminFilterBar>
</AdminPageStickyToolbar>
<AdminTableShell stickyHead>
  …
</AdminTableShell>
```

The toolbar reads `--admin-page-header-h` (set on the wrapper by `AdminPageHeader` via `ResizeObserver`); `AdminTableShell stickyHead` does the same so its `<thead>` sticks just below the toolbar. Pages don't measure pixels.

When `sticky` is set and the page has scrolled past a threshold, `AdminPageHeader` automatically renders a small ghost "back to top" button in the action row. Override with the `backToTop` snippet slot if needed.

**Logs is exempt** — its dense toolbar + virtualized feed don't fit this shape and stay case-by-case.

**Panel portability (`*Panel.svelte` contract):**

```svelte
<!-- Standalone route page: header + tabs + mount the panel -->
<AdminPageHeader kicker="Configuration" title="Active providers" sticky>
  {#snippet actions()}<Button onclick={refresh}>Refresh</Button>{/snippet}
</AdminPageHeader>
<ActiveProvidersPanel store={activeProvidersStore} notify={toasts.notify} />
```

```svelte
<!-- Same panel mounted as a Catalog tab pane -->
<AdminPageHeader kicker="Configuration" title="Catalog" sticky>
  {#snippet tabs()}
    <AdminTabStrip ariaLabel="Catalog sections" tabs={[
      { id: 'providers',        label: 'Providers',        kind: 'pane' },
      { id: 'models',           label: 'Models',           kind: 'pane' },
      { id: 'active-providers', label: 'Active providers', kind: 'pane' }
    ]} bind:active={prefs.activeTab} />
  {/snippet}
</AdminPageHeader>

{#if prefs.activeTab === 'active-providers'}
  <ActiveProvidersPanel store={activeProvidersStore} notify={toasts.notify} />
{/if}
```

```svelte
<!-- Or as a route-style tab that links elsewhere instead of switching pane -->
<AdminTabStrip tabs={[
  { id: 'providers', label: 'Providers', kind: 'pane' },
  { id: 'models',    label: 'Models',    kind: 'pane' },
  { id: 'active',    label: 'Active providers', kind: 'route',
    href: `${base}/active-providers/` }
]} bind:active={prefs.activeTab} />
```

Five rules a panel must satisfy:

1. No `<svelte:head>` / no `<AdminPageHeader>` / no page-level wrapper.
2. State accepted as a prop, not constructed unconditionally inside the panel.
3. URL params are props or namespaced (no top-level `?tab=` ownership).
4. Self-contained section markup; no kicker/title/tabs.
5. Loading / error / empty / toast use shared primitives, with the notifier received from the host.

---

## 4. Phased plan

Phases are **shippable units**: each leaves the app working and is independently reviewable. Each phase has explicit **exit criteria** and a **non-goals** list to keep scope tight.

### Phase 0 — Inventory & freeze (this document)

**Scope:** the document you are reading. Establishes the inventory, the target shared layer, and the per-phase contracts.

**Deliverables**
- `docs/admin-frontend-refactor-plan.md` (this file).
- A short note added to `.cursor/skills/svelte-best-practice/SKILL.md` pointing here.

**Exit criteria**
- Plan reviewed and approved.
- No code changes.

---

### Phase 1 — Shared primitives (no behaviour change)

Build the shared layer once. Adopt it nowhere yet (except trivially).

**New files**

*Feedback primitives:*
- `lib/ui/create-toast-notifier.svelte.ts`
- `lib/ui/InlineDestructiveAlert.svelte` (moved from `features/chat-channels/shared/`)
- `lib/ui/InlineLoading.svelte`
- `lib/ui/InlineEmptyState.svelte`

*Page chrome:*
- `lib/components/page/AdminPageHeader.svelte` — owns the page wrapper (`max-w-[1420px]` left-aligned). Snippet slots: `titleAdornment`, `subtitle` (string **or** snippet), `tabs`, `actions`, `actionsCollapse({ expanded, toggle, ariaControls })`, `backToTop` (auto-rendered when `sticky && scrolled` unless overridden). Covers all 6 variants in §2.2 plus the dense Logs case in §2.4.2. Optional `sticky` prop publishes `--admin-page-header-h` via `ResizeObserver` so two-level sticky toolbars can align (§2.4.5).
- `lib/components/page/AdminPageStickyToolbar.svelte` — sticky second-level bar that mounts under the header at `top: calc(theme(spacing.16) + var(--admin-page-header-h))`. Used by Preferences (section-nav), Catalog/Models (filter bar + table head), Knowledge browse (filters).
- `lib/components/page/AdminTabStrip.svelte` + `AdminTabButton.svelte` — fixed tab strip (variants 1, 2). Tab descriptors carry `kind: 'pane' | 'route'` (per §2.4.6). `route` tabs render as `<a href>`. Has a `recordTab` snippet slot for the dynamic chip (variant 4).
- `lib/components/page/AdminRecordTabChip.svelte` — the icon + truncated-label + X chip; powers Characters' Detail tab.
- `lib/components/page/AdminPageLinkAction.svelte` — anchor-based action button for variant 5 (real `<a href>`, supports middle-click / copy-link).
- `lib/components/page/SectionCard.svelte` — `ADMIN_SECTION_CARD` (solid) variant.
- `lib/components/page/SectionCardMuted.svelte` — `ADMIN_SECTION_CARD_MUTED` (translucent) variant; kept as a deliberate sibling for nested-card use.
- `lib/components/page/SectionScrollNav.svelte` — Preferences-style sticky pill row + scroll-spy + hash deep-link. **Inner nav, not a page-level tab strip.** Stays page-local until promoted; we put the contract here so Phase 4 has a clear target.

*Styling tokens:*
- `lib/styling/admin-tokens.ts` — full token list per §3 diagram (`ADMIN_PAGE_MAX_W`, header / section / form / table tokens + `cnAdminTab` / `cnAdminTableRow` helpers).

*Tab preferences:*
- `lib/preferences/create-tab-preferences.svelte.ts` (generic URL + session tab pref factory).

> **Note on `lib/components/page/table/`:** the table primitives (`AdminTableShell`, `AdminTableHeaderCell`, `AdminFilterBar`, `AdminMasterDetail`, `use-table-sort.svelte.ts`, `use-table-filters.svelte.ts`) are **deferred to Phase 4.5**, after Phase 3 (active providers) but before Phase 5 (CatalogPage decomposition). They're called out here only so the §3 diagram is complete.

**Touched**
- `features/chat-channels/shared/InlineDestructiveAlert.svelte` → re-export from new home (or rewire imports — preferred under no-backwards-compat).
- `features/chat-channels/shared/`: update import paths.

**Non-goals**
- Do **not** touch Preferences/Catalog/Metrics layouts yet.
- Do **not** delete the duplicate unsaved guard yet (Phase 2 work).

**Exit criteria**
- New primitives compile and have storybook-style usage in **one** existing page (Channels-devices is smallest — a good canary).
- `InlineDestructiveAlert` import path updated everywhere it’s currently used.

**Risk:** low. Mostly additive.

---

### Phase 2 — Cross-page consistency adoption

Adopt Phase-1 primitives across **every** page. Behaviour identical, code shrinks.

**Steps**
1. Replace per-page `notify()` + `toast` `$state` + `setTimeout` with `createToastNotifier()` in:
   `PreferencesPage`, `CatalogPage`, `ActiveProvidersPage`, `CharactersPage`, `LogsPage`, `ServerPage`, `ChannelsDevicesPage`, `KnowledgeBrowsePanel`, `chat-channels-controller.svelte.ts`. Standardise timeout at **4500 ms** (drop the 3600 ms outlier in Preferences).
2. Replace inline destructive-error blocks with `<InlineDestructiveAlert />` in 15+ sites listed in §1.8 of the inventory.
3. Replace inline `Loading…` and `<p class="text-muted-foreground">` empty states with `InlineLoading` / `InlineEmptyState`.
4. Replace the kicker + gradient + tab strip in: Characters, Chat channels, Server, Channels-devices, Catalog, plus any others. Knowledge/Graph runs/Characters delete their feature-local header tokens (`KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, the header parts of `character-section-classes.ts`) and use `admin-tokens.ts` directly.
4a. **Standardise the page wrapper**: every page goes through `AdminPageHeader` (which owns the `max-w-[1420px]` left-aligned wrapper) or, for pages that genuinely have no header, an `<AdminPageShell>` equivalent. **Remove `mx-auto … max-w-7xl`** from `PreferencesPage.svelte` (it's the only outlier); Preferences becomes left-aligned at `max-w-[1420px]` like every other page.
4b. **Adopt the dense `actionsCollapse` slot in Logs** so the existing controls-collapse chevron is wired through the shared header instead of the bespoke layout.
4c. **Opt simple pages into single-level sticky** (§2.4.5): pass `sticky` to `<AdminPageHeader>` on Catalog/Providers, Channels-devices, Server, Active providers, Characters browse, Knowledge browse. (Catalog/Models gets two-level sticky in Phase 5; Preferences in Phase 4; Logs is exempt.)
4d. **Adopt the panel-portability contract** (§2.4.6) on every feature that already has a panel/page split — pass the toast notifier and stores in as props, remove any `<svelte:head>` from `*Panel.svelte` files, namespace URL params owned by panels. Tag each tab descriptor with `kind: 'pane'` (or `'route'` for cross-page links). Pages that don't yet split are decomposed in Phases 3–6 — the contract becomes the exit criterion there.
5. **Unify page-level tab URL/session sync.** Replace the four near-identical `lib/preferences/{catalog,server,channels-devices,characters}-preferences.svelte.ts` (the tab parts) and `chat-channels-nav.ts` with one-line `createTabPreferences(...)` calls. Move Knowledge's tab logic and Logs' tab state into `lib/preferences/{knowledge,logs}-tab-preferences.svelte.ts` so **every page-level tabbed page lives in `lib/preferences/`** and **every page-level tabbed page has `?tab=` URL sync** (including Logs, which currently has none — bookmarks should restore the active tab).
6. **Inner navigation is explicitly out of scope here.** Preferences' `#hash` section nav and Graph runs' underline subtab strip with dynamic per-record tabs are **not** migrated to `createTabPreferences` or `AdminTabStrip`. They keep their own state model and components. (Preferences' nav is rebuilt in Phase 4; Graph runs' subtab strip stays as-is unless a second consumer appears.)
7. Adopt `AdminRecordTabChip` for Characters' Detail tab — slotted into `AdminTabStrip` via the `recordTab` snippet. Document the pattern so future "list → open record into a tab" features (likely: Catalog providers, Knowledge documents) reuse it.
8. Adopt `AdminPageLinkAction` for the Preferences → Active providers shortcut and any other place that currently uses `<Button onclick={goto(...)}>` for cross-page navigation. These become real anchors.
9. Collapse `characters-unsaved-guard.svelte.ts` into the canonical `createUnsavedGuard` (the predicate it adds is just `() => prefs.detailMode === 'edit'`); delete the duplicate file.

**Exit criteria**
- `rg -n "function notify\(" admin_frontend/src` returns **zero** matches outside the shared notifier.
- `rg -n "border-destructive/30 bg-destructive/10" admin_frontend/src` returns matches only inside `InlineDestructiveAlert.svelte`.
- `rg -n "characters-unsaved-guard" admin_frontend/src` returns zero matches.
- All pages use `<AdminPageHeader>`. Pages with tabs use `<AdminTabStrip>` inside the `tabs` snippet slot; pages without tabs use only the `actions` slot. Pages with link-style actions use `<AdminPageLinkAction>` instead of `<Button onclick={goto(...)}>`. Logs uses `titleAdornment`, `subtitle` (snippet), and `actionsCollapse`.
- All pages render at `max-w-[1420px]` left-aligned via the shared wrapper. `rg -n "mx-auto" admin_frontend/src/lib/features` returns no matches outside intentional centred children (e.g. icons inside empty-state cards).
- `rg -n "(KNOWLEDGE|GRAPH_RUNS)_HEADER_(KICKER|TITLE|INTRO)" admin_frontend/src` returns zero matches — header tokens live only in `admin-tokens.ts`.
- Every **page-level** tabbed page reads/writes its active tab via `createTabPreferences(...)` from `lib/preferences/`. `rg -n "normalizeTab\b" admin_frontend/src` returns matches only inside `create-tab-preferences.svelte.ts`.
- Every **page-level** tabbed page has `?tab=<id>` in the URL after switching (verifiable manually on Logs, Knowledge, Chat channels — the three that previously diverged).
- Inner navigation (Preferences `#hash`, Graph runs subtab strip) is left untouched in Phase 2 and is **not** present in any of the above checks.
- Catalog/Providers, Channels-devices, Server, Active providers, Characters browse, Knowledge browse render with `sticky` headers that stay visible while their bodies scroll. `rg -n "KNOWLEDGE_PAGE_STICKY_HEADER" admin_frontend/src` returns matches only inside `admin-tokens.ts` (or zero, if the constant is dropped in favour of the prop).
- `*Panel.svelte` files contain **no** `<svelte:head>` and **no** `<AdminPageHeader>` (`rg -n "(svelte:head|AdminPageHeader)" admin_frontend/src/lib/features/**/*Panel.svelte` returns zero matches).
- All `AdminTabStrip` tab descriptors declare `kind: 'pane' | 'route'`.

**Risk:** low–medium. Mostly mechanical, but every page is touched. Snapshot screenshots before/after recommended.

---

### Phase 3 — Active-providers extraction

Kill the dead `{:else}` branch in CatalogPage and the standalone `ActiveProvidersPage`/store duplication.

**New files**
- `lib/catalog/active-providers/ActiveProvidersPanel.svelte`
- `lib/catalog/active-providers/active-providers-store.svelte.ts`
- `lib/catalog/active-providers/active-providers-add-dialog.svelte`
- `lib/catalog/active-providers/active-providers-scan-dialog.svelte`
- `lib/catalog/catalog-reload.ts` (shared catalog-reload orchestration)
- `lib/catalog/include-unknown-model.ts` (moved out of `PreferencesPage`)

**Touched / deleted**
- `lib/features/catalog/ActiveProvidersPage.svelte` — becomes a thin shell that mounts `ActiveProvidersPanel`.
- `lib/features/catalog/CatalogPage.svelte` — delete the dead L913+ branch; if we want a third tab, mount the same `ActiveProvidersPanel` (decide during phase). Replace inline catalog-reload with the shared helper.
- `lib/features/preferences/PreferencesPage.svelte` — replace inline `loadActiveProviders` + provider-id `Set`s with the shared store; replace inline `reloadCatalogForPage` with `catalog-reload.ts`.
- `lib/features/characters/state/characters-controller.svelte.ts` — same.

**Exit criteria**
- One source of truth for active-providers data and CRUD UI.
- `rg -n "listActiveProviders" admin_frontend/src` returns matches only inside the shared store and the Dashboard read-only call.
- `rg -n "reloadModelCatalog" admin_frontend/src` returns matches only inside `catalog-reload.ts` and the API client.
- Dead branch in `CatalogPage` removed.

**Risk:** medium. Dialog + table behaviour must be preserved exactly.

---

### Phase 4 — Decompose `PreferencesPage`

Largest file in the project. Apply SKILL.md §1–§9 fully.

**Target layout**

```text
features/preferences/
  PreferencesPage.svelte            # thin shell (target: < 200 lines)
  state/
    preferences-controller.svelte.ts        # load/save/reset, dirty, edits-for-save
    preferences-section-nav.svelte.ts       # scroll-spy + hash deep-link
  shared/
    preferences-ui.ts                       # local tokens that re-export admin-tokens
  sections/
    ModelsSection.svelte                    # default chat/stt/tts + tuning profile
    MediaSection.svelte                     # input/output modality grids
    MemorySection.svelte                    # memory LLM/embedding + retrieval + reranker
    KnowledgeSection.svelte                 # knowledge embedding/answering/chunking
    TuningProfilesSection.svelte            # CRUD list of profiles
  widgets/
    ReloadCatalogButton.svelte              # adopts shared catalog-reload helper
```

**Steps**
1. Move `editsForSave`, `clonePrefs`, normalisation, and load/save into `state/preferences-controller.svelte.ts`.
2. Move scroll-spy + hash deep-link into `preferences-section-nav.svelte.ts` and render via `<SectionScrollNav>` from `components/page/`.
3. Replace the 20+ raw `<input>` / `<select>` blocks with `FormField` + `<input class={ADMIN_INPUT}>` etc. (decision: prefer `FormField` for label+input pairs; raw `class={ADMIN_INPUT}` only when no label is needed).
4. Each `<section>` in the current file becomes one component under `sections/`.
5. Delete `lib/features/preferences/PreferencesPage.svelte`'s inline `notify`, active-provider sets, `loadActiveProviders`, `reloadCatalogForPage`, `includeUnknownModel` — they live in the shared layer after Phases 2 and 3.
6. **Drop the `mx-auto … max-w-7xl` wrapper.** Preferences becomes left-aligned at `max-w-[1420px]` like every other page (§2.4.1).
7. **Wire two-level sticky** (§2.4.5): `<AdminPageHeader sticky>` carries the title + Save/Reset/Active-providers actions; `<AdminPageStickyToolbar>` wraps the section-nav so it sticks **below** the header instead of replacing it. The page header no longer disappears once the user scrolls.

**Exit criteria**
- `PreferencesPage.svelte` ≤ 200 lines.
- All sections render identically; dirty diff produces the same `editsForSave` payload (verifiable against the existing API).
- Page is left-aligned at `max-w-[1420px]` — no `mx-auto` on its wrapper.
- Two-level sticky is wired: scrolling the body keeps the **page title + actions visible** and the section-nav stuck immediately below. The previous behaviour (header scrolling away entirely) is gone.
- Each `sections/*.svelte` is a `*Panel`-shaped component (no `<svelte:head>`, no page-level chrome inside) — they're not literally portable as tabs in another page (they're tied to the preferences draft state) but they follow the panel shape so future re-mounting is trivial.

**Risk:** high. Largest single change. Recommend doing this on a feature branch and walking through every section manually.

---

### Phase 4.5 — Table & list primitives

Lands **after** Phase 3 (active providers extracted) and **before** Phase 5 (CatalogPage decomposition), so Catalog can adopt the new primitives in the same PR that splits it.

**New files**
- `lib/components/page/table/AdminTableShell.svelte`
- `lib/components/page/table/AdminTableHeaderCell.svelte`
- `lib/components/page/table/AdminFilterBar.svelte` (+ `AdminFilterBar.Search` / `AdminFilterBar.Select` sub-components)
- `lib/components/page/table/AdminMasterDetail.svelte`
- `lib/components/page/table/use-table-sort.svelte.ts`
- `lib/components/page/table/use-table-filters.svelte.ts`

**Steps**
1. Build the primitives with no consumer; unit-test sort cycling and `aria-sort`.
2. Adopt in `ActiveProvidersPanel.svelte` first (smallest table, validates the API).
3. Adopt in Server `WorkspacesTab.svelte` / `GatewaysTab.svelte` and Channels-devices tabs (basic tables, low risk).
4. Wire `AdminMasterDetail` into Logs and Knowledge browse — the page-level layouts already have list+detail splits; this just consolidates the toggle + scroll-region pattern.
5. Leave Catalog and Graph runs for Phases 5 / future — they migrate as part of their decomposition phases.

**Sticky integration**
- `AdminTableShell stickyHead` reads `--admin-page-header-h` (set by `AdminPageHeader sticky`) and adds the height of any sibling `AdminPageStickyToolbar` so the table `<thead>` sticks at the right `top: …` automatically.
- Pages with both `AdminPageStickyToolbar` (filter bar) and `AdminTableShell stickyHead` (table head) get **two-level sticky for free** — header at `top-16`, filter bar below it, table head below the filter bar.

**Non-goals**
- **No** monolithic `<AdminTablePanel>` that owns columns config. Pages own their cell rendering; the primitives only standardise chrome (shell, sort headers, filter bar, master-detail).
- Logs' virtualized log feed is **exempt** — it stays a feature-local component.
- Graph runs' bespoke "open run as a record tab" pattern is unchanged here (handled in its own dedicated improvements).

**Exit criteria**
- 3+ pages render through `AdminTableShell` (Active providers, Server tabs, Channels-devices tabs).
- `useTableSort` + `useTableFilters` URL-sync produces shareable bookmarks for Catalog filters and Graph runs filters once they migrate (Phase 5+).
- `rg -n "<th[^>]*aria-sort" admin_frontend/src` returns matches only inside `AdminTableHeaderCell.svelte`.
- At least one consumer (planned: Active providers) renders with sticky table head correctly aligned below a sticky page header — verified by scroll testing.

**Risk:** medium. Sort/filter state shape must accommodate the variety of pages without forcing a least-common-denominator API.

---

### Phase 5 — Decompose `CatalogPage`

Same playbook as Phase 4. After Phase 3 the active-providers branch is already gone, so this phase focuses on providers + models tabs.

**Target layout**

```text
features/catalog/
  CatalogPage.svelte                       # thin shell
  state/
    catalog-controller.svelte.ts           # tab state, filters URL sync, data load
  browse/
    ProvidersTab.svelte
    ModelsTab.svelte
    ModelsFilterBar.svelte
  shared/
    catalog-pricing.ts                     # pricing helpers (moved out of page)
    catalog-filter-ui.ts                   # filter labels, kind/class lookups
```

**Exit criteria**
- `CatalogPage.svelte` ≤ 200 lines.
- Active-providers tab — if kept — mounts `ActiveProvidersPanel` from the shared layer.
- Both tables (providers, models) render through `AdminTableShell` + `AdminTableHeaderCell` from Phase 4.5; the filter bar uses `AdminFilterBar`; sort + filter state comes from `useTableSort` + `useTableFilters`.
- Models filter URL sync handled by `catalog-controller.svelte.ts` via `useTableFilters({ urlSync: true })`.
- Catalog/Models renders with **two-level sticky**: header (kicker + title + tabs + Refresh/Reload) at `top-16`, filter bar in `<AdminPageStickyToolbar>` below it, table head sticky below the toolbar via `AdminTableShell stickyHead`. Catalog/Providers gets single-level sticky (header only).
- `ProvidersTab.svelte` and `ModelsTab.svelte` are panel-shaped (`*Tab.svelte` is fine as a name; the contract from §2.4.6 still applies — no `<svelte:head>`, no page wrapper, state passed in).

**Risk:** medium. Two tables and a filter bar; mostly markup extraction.

---

### Phase 6 — Decompose `MetricsPage` & Dashboard

**Metrics**
- `state/metrics-controller.svelte.ts` (polling + tick state).
- `MetricCard.svelte` and friends — eliminate the `:global(.metric-card …)` block by moving styles into the component.
- Split out `MetricsPanel.svelte` (the body) from `MetricsPage.svelte` (the route shell). The panel follows §2.4.6 so it can later be embedded as a tab in Server or a future Observability page.
- Adopt shared header / inline-feedback primitives. `sticky` header is opt-in (recommend yes if the body scrolls).

**Dashboard (`routes/+page.svelte`)**
- Move data fetch into `lib/features/dashboard/state/dashboard-controller.svelte.ts`.
- Render via a `DashboardPanel.svelte` so the route is a thin shell. Reuse `ActiveProvidersPanel` (read-only via a prop if needed) and any other already-portable panel instead of re-loading providers locally.

**Exit criteria**
- `MetricsPage.svelte` ≤ 200 lines, no `:global` for layout.
- `routes/+page.svelte` ≤ 80 lines (composition root only).
- `MetricsPanel.svelte` and `DashboardPanel.svelte` exist and follow the §2.4.6 portability contract (no `<svelte:head>`, state accepted as props, namespaced URL params if any).

**Risk:** low–medium.

---

### Phase 7 — Form primitives + Modal/Dialog convergence

After all pages are split, finish the styling story.

**Form primitives**
- Audit remaining raw `<input class="h-10 …">` sites; move them onto `FormField` or `<input class={ADMIN_INPUT}>`.
- Decide whether `Modal.svelte`’s `[&_input]:…` descendant styling can be deleted once forms inside modals use `FormField` consistently. (It can — that ugly Tailwind blob in `Modal.svelte` L105 is a maintenance bomb.)

**Modal vs Dialog**
- Pick one. Recommendation: **standardise on shadcn `Dialog`** because (a) Knowledge already uses it and (b) it has accessibility primitives we’d otherwise hand-roll.
- Migrate: every `Modal` call site → `Dialog`. Delete `lib/ui/Modal.svelte`.
- (Optional rule under no-backward-compat: rip and replace; do not keep both.)

**Preferences-module placement**
- Decide whether feature-local prefs (`logs/state/logs-preferences.svelte.ts`, `chat-channels/shared/...`, knowledge’s split files) should standardise to `lib/preferences/<feature>-preferences.svelte.ts`. Recommendation: **yes**, since `lib/preferences/keys.ts` already centralises keys.

**Exit criteria**
- Single dialog component family across the app.
- `rg -n "h-10 rounded-md border border-input bg-background" admin_frontend/src` returns matches only inside `admin-tokens.ts` and `FormField`.
- `lib/preferences/` lists one `*-preferences.svelte.ts` per page.

**Risk:** medium (Modal→Dialog is invasive but mechanical).

---

## 5. Conventions appendix (post-refactor)

These rules are enforced by review after Phase 7. Add them to `svelte-best-practice/SKILL.md` once stable.

1. **No page-local toast helpers.** Use `createToastNotifier()`.
2. **No raw `border-destructive/30 bg-destructive/10` blocks.** Use `InlineDestructiveAlert`.
3. **No inline `<p class="text-muted-foreground">Loading…</p>`** in pages. Use `InlineLoading`.
4. **No hand-rolled tab strips for page-level tabs.** Use `AdminPageHeader` + `AdminTabStrip` + `AdminTabButton`. "Open record" tabs use `AdminRecordTabChip` slotted into the strip.
4a. **Every page-level tabbed page has `?tab=` URL sync** via `createTabPreferences(...)` in `lib/preferences/`. No feature-local tab modules. Bookmarks must restore the active tab.
4b. **Page-level tabs and inner navigation are different patterns.** Inner section navigation (e.g. Preferences `#hash` scroll-spy) uses `SectionScrollNav`, not `AdminTabStrip`, and uses hash anchors, not `?tab=`. Inner subtab strips with dynamic per-record tabs (Graph runs) stay feature-local until a second consumer appears.
4c. **Cross-page navigation actions in the page header are anchors, not buttons.** Use `AdminPageLinkAction` (which renders `<a href>`); never `<Button onclick={goto(...)}>` for "go to another page" actions. Middle-click and "copy link" must work.
5. **No inline `h-10 rounded-md border border-input …` soup.** Use `FormField` (label+input) or `class={ADMIN_INPUT}` (bare input).
6. **No `:global(...)` rules in feature pages** for layout. If global is required, it lives in `app.css` or in a tiny presentational component with scoped styles.
7. **Tab + URL preferences live in `lib/preferences/<feature>-preferences.svelte.ts`.**
8. **Active providers, catalog reload, model catalog merge** — shared in `$lib/catalog/`. No feature-local re-implementation.
9. **Unsaved-changes guard** — one canonical `createUnsavedGuard`. Page-specific predicates are passed in.
10. **One dialog family** — `$lib/components/ui/dialog/`. `Modal.svelte` is removed.
11. **Pages target ≤ 200 lines.** Above that, decompose per SKILL.md §1, §8.
12. **Page wrapper** — every page is `max-w-[1420px]` left-aligned via `<AdminPageHeader>` / `<AdminPageShell>`. **No `mx-auto` on page wrappers.**
13. **Header tokens** — kicker / title / intro come from `admin-tokens.ts`. No feature-local copies (`KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, header-related entries in `character-section-classes.ts`) are allowed.
14. **Section cards** — two blessed variants: `<SectionCard>` (solid, primary grouping) and `<SectionCardMuted>` (translucent, nested-card use). No third recipe.
15. **Tables** — page-level tables use `AdminTableShell` + `AdminTableHeaderCell` for chrome; `AdminFilterBar` for filter rows; `AdminMasterDetail` for list+detail layouts; `useTableSort` / `useTableFilters` for state. No bespoke sort-header or filter-bar markup. Logs' virtualized log feed is exempt.
16. **Dense / collapsible action toolbars** — `AdminPageHeader` `actionsCollapse` slot. The collapsed region uses `hidden`, not `{#if}`, so `aria-controls` stays valid (per SKILL.md §10).
17. **Sticky page headers** — opt in via `<AdminPageHeader sticky>` (which publishes `--admin-page-header-h`). Two-level sticky uses `<AdminPageStickyToolbar>` for the second bar; sticky table head uses `<AdminTableShell stickyHead>`. **Pages must not hide the page title in favour of a lower bar** — the header itself stays visible. Logs is the only sanctioned exempt page.
18. **Panel portability** — every page's tab content is a `*Panel.svelte` (or `*Tab.svelte`) that satisfies the five rules in §2.4.6: no `<svelte:head>`, no `<AdminPageHeader>`, no page wrapper, state-as-prop, namespaced URL params, host-supplied notifier. Tab descriptors declare `kind: 'pane' | 'route'` so a tab can be either local content or a real anchor link to another page.

---

## 6. Suggested execution order & sizing

| Phase | Files added | Files touched | Files removed | Effort |
|---|---|---|---|---|
| 0 | 1 | 1 | 0 | XS |
| 1 | ~14 | ~5 | 0 | M |
| 2 | 0 | ~25 | 1 (`characters-unsaved-guard.svelte.ts`) + feature-local header-token files | M |
| 3 | ~6 | ~5 | 1 (dead Catalog branch) | M |
| 4 | ~10 | ~5 | 0 (PreferencesPage shrinks) | L |
| 4.5 | ~6 | ~5 (Active providers, Server tabs, Channels-devices tabs, Logs, Knowledge) | 0 | M |
| 5 | ~7 | ~3 | 0 | M |
| 6 | ~5 | ~2 | 0 | M |
| 7 | varies | ~all dialog sites | `Modal.svelte` | M |

Recommended cadence: ship one phase per PR. Phases 1–3 are prerequisites; Phases 4–7 can be re-ordered if needed (e.g. tackle Catalog before Preferences if you want a quicker win), but **Phase 4.5 must precede Phase 5** so Catalog adopts the table primitives in the same decomposition.

---

## 7. Open decisions (need a call before each phase)

**Resolved (recorded for traceability):**

- **§2.4.1 — page alignment:** standardise on `max-w-[1420px]` left-aligned. Preferences becomes left-aligned in Phase 4.
- **§2.4.2 — Logs dense header:** Option A (snippet-rich `AdminPageHeader` with `titleAdornment`, `subtitle`-as-snippet, `actions`, `actionsCollapse`).
- **§2.4.3 — table primitives:** Option 2 (composition primitives, not monolithic table component). New Phase 4.5.
- **§2.4.4 — section cards:** keep both `<SectionCard>` (solid) and `<SectionCardMuted>` (translucent) as deliberate variants.
- **§2.4.5 — sticky headers:** Option SA — one `sticky` prop on `AdminPageHeader` plus `--admin-page-header-h` CSS-var spine, with `<AdminPageStickyToolbar>` for the second level and `AdminTableShell stickyHead` for sticky table heads. Auto `backToTop` slot. Phased adoption: contract in Phase 1, simple pages opt in during Phase 2, Preferences fixed in Phase 4 (header no longer disappears), table-head sticky in Phase 4.5, Catalog/Models two-level in Phase 5. Logs exempt.
- **§2.4.6 — panel portability:** five-rule contract enforced; `AdminTabStrip` tab descriptors carry `kind: 'pane' | 'route'`. Adopted as a Phase 2 convention; remaining decompositions (Phases 3–6) produce panels that already follow it. Active providers, Metrics, Dashboard, and the Server tabs become explicitly portable.

**Still open:**

- **Phase 3:** Should the Catalog page keep an active-providers tab, or is the dedicated `/active-providers/` route the only entry point? (Recommendation: only the dedicated route — the dead branch suggests this was already the intent.)
- **Phase 4:** Should preferences-section navigation (`SectionScrollNav`) live in `components/page/` shared from day one, or stay feature-local until a second consumer appears? (Recommendation: ship the shared component in Phase 1, but Preferences is the only consumer until proven otherwise — that's fine.)
- **Phase 7:** `Modal` → `Dialog` rip-and-replace, or freeze new work on `Modal` and migrate opportunistically? (Recommendation: rip-and-replace — fits the no-backward-compat rule.)

---

## 8. Related docs

- `docs/admin-ui.md` — admin UI overview (dev/build/runtime routes).
- `.cursor/skills/svelte-best-practice/SKILL.md` — per-page conventions; this plan is the cross-page complement.
- `docs/refactor-review-map.md` — historical refactor reviews (context).
