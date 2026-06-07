<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import { Pause, Play, Search, Trash2, X } from '@lucide/svelte';
  import type { LogTimeRange } from '$lib/api/logs';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminMasterDetail from '$lib/components/page/table/AdminMasterDetail.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import { ADMIN_INPUT, ADMIN_SEARCH_FIELD } from '$lib/styling/admin-tokens';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import type { ToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import { cn } from '$lib/utils';
  import { LOG_LEVELS, LOG_TIME_RANGES } from '$lib/api/logs';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import { logLevelAccentClass } from './shared/logs-classes';
  import LogLevelIcon from './shared/LogLevelIcon.svelte';
  import LogsDetailPanel from './LogsDetailPanel.svelte';
  import LogsFiltersPanel from './LogsFiltersPanel.svelte';
  import LogsTablePanel from './LogsTablePanel.svelte';
  import { LOGS_FILTER_REGION_ID } from './shared/logs-a11y';
  import { setupLogsPageRuntime } from './shared/logs-page-lifecycle';
  import { isLogTimeRange, type RenderLogRow } from './shared/logs-ui';

  // Portable logs body. The page header chrome (folder button, counts subtitle,
  // filter collapse chevron) lives in the host `LogsPage.svelte` because Graph
  // runs shares that header as the Logs page's second tab. `ctrl`/`prefs`/`notify`
  // are owned by the host and passed down so both header and body stay in sync.
  let {
    ctrl,
    prefs,
    notify
  }: { ctrl: LogsPageController; prefs: LogsPreferences; notify: ToastNotifier['notify'] } = $props();

  // Auto-follow new logs only while pinned to the very top (newest-first feed); once
  // the user scrolls down to read, stop yanking them back to the top.
  let atTop = $state(true);
  let tableScroller = $state<HTMLDivElement | null>(null);
  let clearLogsConfirmOpen = $state(false);

  // Sticky offsets clear the shell bar (4rem) + the sticky page header + the sticky
  // filter toolbar (heights published as CSS vars). The toolbar term is gated on the
  // collapse flag we own rather than read purely from the published var: a collapsed
  // toolbar is 0px tall, but ResizeObserver does not reliably re-publish that shrink,
  // which would otherwise leave a dead gap above the table head when collapsed.
  const stickyToolbarTerm = $derived(
    prefs.controlsCollapsed ? '0px' : 'var(--admin-page-sticky-toolbar-h, 0px)'
  );
  const tableStickyTop = $derived(
    `calc(4rem + var(--admin-page-header-h, 0px) + ${stickyToolbarTerm})`
  );
  const detailStickyTop = $derived(`calc(${tableStickyTop} + 0.75rem)`);
  // Fixed height (not just max-height) so the panel always fills the visible page
  // area even with little data; its inner body scrolls when content overflows.
  const detailHeight = $derived(`calc(100vh - ${tableStickyTop} - 1.5rem)`);

  const timeRangeLabels: Record<LogTimeRange, string> = {
    '1h': '1 hr',
    '2h': '2 hrs',
    '4h': '4 hrs',
    '1d': '1 day',
    '2d': '2 days',
    '3d': '3 days',
    all: 'All'
  };

  function selectRow(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    tableScroller?.focus();
  }

  function openRowDetails(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    prefs.detailPanelOpen = true;
    tableScroller?.focus();
  }

  // Merged "Last session" + time-range picker: "last" pins to the latest server
  // startup; any other value is a rolling past-window.
  function onSessionRangeChange(value: string) {
    if (value === 'last') {
      prefs.lastSessionOnly = true;
    } else if (isLogTimeRange(value)) {
      prefs.lastSessionOnly = false;
      prefs.logTimeRange = value;
    } else {
      return;
    }
    void ctrl.reloadLiveTail();
  }

  function requestClearLogs() {
    clearLogsConfirmOpen = true;
  }

  function confirmClearLogs() {
    clearLogsConfirmOpen = false;
    void ctrl.clearAllLogs();
  }

  $effect(() => {
    if (!ctrl.initialized) return;
    void prefs.paused;
    void prefs.sortColumn;
    void prefs.sortDir;
    void prefs.activeSources;
    void prefs.activeChannel;
    void prefs.levelFilter;
    void prefs.searchText;
    void prefs.scopeDeviceId;
    void prefs.scopeMsgId;
    void prefs.scopeMethod;
    void prefs.detailPanelOpen;
    void prefs.controlsCollapsed;
    void prefs.lastSessionOnly;
    void prefs.logTimeRange;
    prefs.persistToSession();
  });

  $effect(() => {
    ctrl.rows.length;
    ctrl.visibleRows.length;
    prefs.sortColumn;
    prefs.sortDir;
    if (!ctrl.initialized || !atTop) return;
    void tick().then(() => {
      if (typeof window !== 'undefined') window.scrollTo({ top: 0 });
    });
  });

  onMount(() => {
    const onScroll = () => (atTop = window.scrollY <= 4);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  });

  onMount(() =>
    setupLogsPageRuntime({
      prefs,
      ctrl,
      urlMsgId: page.url.searchParams.get('msg_id')
    })
  );
</script>

<!-- Controls live on their own sticky line below the shared page header.
     Collapsing hides the region's content (and zeroes the bar's padding/border)
     rather than the toolbar element itself: a `display:none` element stops
     emitting ResizeObserver notifications, which would freeze the published
     toolbar height. Keeping the element keeps the height var in sync and keeps
     the aria-controls target in the DOM while the chevron (in the host header)
     still references it. -->
<AdminPageStickyToolbar class={cn(prefs.controlsCollapsed && 'border-0 py-0')}>
  <div
    id={LOGS_FILTER_REGION_ID}
    role="region"
    aria-label="Log controls"
    class={cn(prefs.controlsCollapsed ? 'hidden' : 'flex flex-col gap-3')}
  >
    <div class="flex min-w-0 flex-wrap items-center gap-2">
      <div class="flex items-center gap-1" role="group" aria-label="Filter log levels">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Level:</span>
        {#each LOG_LEVELS as level (level)}
          {@const active = prefs.levelIsActive(level)}
          <Button
            size="icon"
            variant={active ? 'secondary' : 'ghost'}
            class="size-7 shrink-0 shadow-none"
            title={level}
            aria-label={`${active ? 'Hide' : 'Show'} ${level} logs`}
            aria-pressed={active}
            onclick={() => prefs.toggleLevel(level)}
          >
            <LogLevelIcon
              level={level}
              size={14}
              class={cn('shrink-0', active ? logLevelAccentClass(level) : 'opacity-40')}
            />
          </Button>
        {/each}
      </div>
      <label class={ADMIN_SEARCH_FIELD}>
        <Search size={15} class="text-muted-foreground" />
        <input
          class="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
          placeholder="Search logs..."
          value={prefs.searchText}
          oninput={ctrl.onSearchInput}
        />
        {#if prefs.searchText}
          <button
            class="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
            type="button"
            aria-label="Clear search"
            onclick={() => void ctrl.clearSearch()}
          >
            <X size={14} />
          </button>
        {/if}
      </label>
      <Button
        variant="outline"
        size="icon"
        class="size-8"
        title={prefs.paused ? 'Resume live tail' : 'Pause live tail'}
        aria-label={prefs.paused ? 'Resume live tail' : 'Pause live tail'}
        onclick={() => prefs.togglePause()}
      >
        {#if prefs.paused}
          <Play size={15} />
        {:else}
          <Pause size={15} />
        {/if}
      </Button>
      {#if ctrl.blocksLiveTail}
        <Button variant="outline" size="sm" onclick={() => void ctrl.clearAllFilters()}>
          Clear filters
        </Button>
      {/if}
      <label class="flex items-center gap-1.5 font-sans text-sm text-muted-foreground">
        <span class="sr-only">Time window</span>
        <select
          class={cn(ADMIN_INPUT, 'min-w-[7rem] px-2')}
          value={prefs.lastSessionOnly ? 'last' : prefs.logTimeRange}
          onchange={(event) =>
            onSessionRangeChange((event.currentTarget as HTMLSelectElement).value)}
          aria-label="Log time window"
          title="Show logs from the last session or a rolling time window"
        >
          <option value="last">Last session</option>
          {#each LOG_TIME_RANGES as r (r)}
            <option value={r}>{timeRangeLabels[r]}</option>
          {/each}
        </select>
      </label>
      <span class="hidden h-6 w-px bg-border md:block"></span>
      <Button
        variant="destructive"
        size="icon"
        class="size-8"
        title={ctrl.clearingLogs ? 'Clearing logs…' : 'Clear all logs'}
        aria-label="Clear all logs"
        onclick={requestClearLogs}
        disabled={ctrl.clearingLogs}
      >
        <Trash2 size={15} />
      </Button>
    </div>

    <LogsFiltersPanel {prefs} {ctrl} />
  </div>
</AdminPageStickyToolbar>

{#if ctrl.error}
  <InlineDestructiveAlert message={ctrl.error} class="px-3 py-2 text-sm" />
{:else if ctrl.pollError}
  <div
    class="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-sans text-sm text-amber-700 dark:text-amber-300"
  >
    {ctrl.pollError}
  </div>
{/if}

<AdminMasterDetail bind:detailOpen={prefs.detailPanelOpen} scroll="page">
  {#snippet list()}
    <LogsTablePanel
      {ctrl}
      detailPanelOpen={prefs.detailPanelOpen}
      stickyHeadTop={tableStickyTop}
      sortColumn={prefs.sortColumn}
      sortDir={prefs.sortDir}
      onToggleSort={(col) => prefs.toggleSortColumn(col)}
      bind:scroller={tableScroller}
      onSelectRow={selectRow}
      onOpenRowDetails={openRowDetails}
      onTableKeydown={(event) => ctrl.handleTableKeydown(event, () => tableScroller)}
      onFilterToMessage={ctrl.filterToMessage}
    />
  {/snippet}
  {#snippet detail()}
    <!-- Sticky so the detail stays in view while the table scrolls the document. -->
    <LogsDetailPanel
      activeRow={ctrl.activeRow}
      onClose={() => (prefs.detailPanelOpen = false)}
      onNotify={notify}
      class="sticky self-start z-20"
      style="top: {detailStickyTop}; height: {detailHeight};"
    />
  {/snippet}
</AdminMasterDetail>

<Dialog.Root
  open={clearLogsConfirmOpen}
  onOpenChange={(next) => {
    if (!next && !ctrl.clearingLogs) clearLogsConfirmOpen = false;
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Clear all logs?</Dialog.Title>
      <Dialog.Description>This truncates workspace, gateway, and stderr log files.</Dialog.Description>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">This action cannot be undone.</p>
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.clearingLogs} onclick={() => (clearLogsConfirmOpen = false)}>
        Cancel
      </Button>
      <Button variant="destructive" disabled={ctrl.clearingLogs} onclick={confirmClearLogs}>
        Clear logs
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
