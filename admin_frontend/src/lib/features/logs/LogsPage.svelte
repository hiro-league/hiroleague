<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import {
    ArrowDownUp,
    ChevronDown,
    ChevronUp,
    FolderOpen,
    PanelRightClose,
    PanelRightOpen,
    Pause,
    Play,
    Search,
    Trash2,
    X
  } from '@lucide/svelte';
  import type { LogTimeRange } from '$lib/api/logs';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminMasterDetail from '$lib/components/page/table/AdminMasterDetail.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import { ADMIN_HEADER_INTRO, ADMIN_INPUT, ADMIN_SEARCH_FIELD } from '$lib/styling/admin-tokens';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import { cn } from '$lib/utils';
  import { LOG_TIME_RANGES } from '$lib/api/logs';
  import LogsDetailPanel from './LogsDetailPanel.svelte';
  import LogsFiltersPanel from './LogsFiltersPanel.svelte';
  import LogsTablePanel from './LogsTablePanel.svelte';
  import { createLogsPageController } from './state/logs-controller.svelte';
  import { createLogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import { LOGS_DETAIL_PANEL_ID, LOGS_FILTER_REGION_ID } from './shared/logs-a11y';
  import { setupLogsPageRuntime } from './shared/logs-page-lifecycle';
  import { isLogTimeRange, type RenderLogRow } from './shared/logs-ui';

  const prefs = createLogsPreferences();
  const ctrl = createLogsPageController({ prefs });

  let autoScroll = $state(true);
  let tableScroller = $state<HTMLDivElement | null>(null);
  let clearLogsConfirmOpen = $state(false);
  const toasts = createToastNotifier();
  const notify = toasts.notify;

  const timeRangeLabels: Record<LogTimeRange, string> = {
    '1h': '1 hr',
    '2h': '2 hrs',
    '4h': '4 hrs',
    '1d': '1 day',
    '2d': '2 days',
    '3d': '3 days',
    all: 'All'
  };

  function openLogsFolder() {
    void ctrl.openLogsFolder(notify);
  }

  function selectRow(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    tableScroller?.focus();
  }

  function openRowDetails(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    prefs.detailPanelOpen = true;
    tableScroller?.focus();
  }

  function scrollToEdge() {
    if (!tableScroller || !autoScroll || ctrl.visibleRows.length === 0) return;
    if (prefs.sortOrder === 'newest') {
      tableScroller.scrollTop = 0;
    } else {
      tableScroller.scrollTop = tableScroller.scrollHeight;
    }
  }

  function toggleLastSessionOnly() {
    prefs.lastSessionOnly = !prefs.lastSessionOnly;
    void ctrl.reloadLiveTail();
  }

  function onLogTimeRangeChange(value: LogTimeRange) {
    prefs.logTimeRange = value;
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
    void prefs.sortOrder;
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
    prefs.sortOrder;
    if (!ctrl.initialized || !autoScroll) return;
    void tick().then(scrollToEdge);
  });

  onMount(() =>
    setupLogsPageRuntime({
      prefs,
      ctrl,
      urlMsgId: page.url.searchParams.get('msg_id')
    })
  );
</script>

<AdminPageHeader
  kicker="Operations"
  title="Logs"
  wrapperClass="flex h-full min-h-0 max-w-[2000px] flex-col gap-4 overflow-hidden"
  collapseExpanded={!prefs.controlsCollapsed}
  onToggleCollapse={() => prefs.toggleControlsCollapsed()}
  collapseAriaControls={LOGS_FILTER_REGION_ID}
>
  {#snippet titleAdornment()}
    <button
      class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-40"
      type="button"
      disabled={!ctrl.layout?.log_dir?.trim()}
      onclick={openLogsFolder}
      title={ctrl.layout?.log_dir?.trim()
        ? `Open logs folder: ${ctrl.layout.log_dir.trim()}`
        : 'Open logs folder'}
      aria-label={ctrl.layout?.log_dir?.trim()
        ? `Open logs folder: ${ctrl.layout.log_dir.trim()}`
        : 'Open logs folder'}
    >
      <FolderOpen size={13} />
    </button>
  {/snippet}

  {#snippet subtitleSlot()}
    <p class={cn(ADMIN_HEADER_INTRO, 'mt-1 font-sans text-xs')}>
      {ctrl.visibleRows.length} visible / {ctrl.rows.length} loaded
      {#if ctrl.searchBusy}
        <span class="ml-2 text-primary">Searching...</span>
      {:else if ctrl.isSearchMode || ctrl.hasScopeFilters}
        <span class="ml-2 text-primary">Filtered</span>
      {/if}
    </p>
  {/snippet}

  {#snippet actions()}
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
    <Button variant="outline" size="sm" onclick={() => prefs.toggleSort()}>
      <ArrowDownUp size={15} />
      {prefs.sortOrder === 'newest' ? 'Newest first' : 'Oldest first'}
    </Button>
    <Button variant="outline" size="sm" onclick={() => prefs.togglePause()}>
      {#if prefs.paused}
        <Play size={15} />
        Resume
      {:else}
        <Pause size={15} />
        Pause
      {/if}
    </Button>
    {#if ctrl.blocksLiveTail}
      <Button variant="outline" size="sm" onclick={() => void ctrl.clearAllFilters()}>
        Clear filters
      </Button>
    {/if}
    <Button
      variant={autoScroll ? 'secondary' : 'outline'}
      size="sm"
      onclick={() => (autoScroll = !autoScroll)}
    >
      {#if prefs.sortOrder === 'newest'}
        <ChevronUp size={15} />
      {:else}
        <ChevronDown size={15} />
      {/if}
      Auto-scroll {autoScroll ? 'on' : 'off'}
    </Button>
    <Button
      variant={prefs.lastSessionOnly ? 'secondary' : 'outline'}
      size="sm"
      onclick={toggleLastSessionOnly}
    >
      Last session {prefs.lastSessionOnly ? 'on' : 'off'}
    </Button>
    <label class="flex items-center gap-1.5 font-sans text-sm text-muted-foreground">
      <span class="sr-only">Time range</span>
      <select
        class={cn(
          ADMIN_INPUT,
          'min-w-[5.5rem] px-2 disabled:cursor-not-allowed disabled:opacity-50'
        )}
        disabled={prefs.lastSessionOnly}
        value={prefs.logTimeRange}
        onchange={(event) => {
          const v = (event.currentTarget as HTMLSelectElement).value;
          if (isLogTimeRange(v)) onLogTimeRangeChange(v);
        }}
        aria-label="Log time range"
        title={prefs.lastSessionOnly ? 'Disabled while Last session is on' : 'Show logs from this window'}
      >
        {#each LOG_TIME_RANGES as r (r)}
          <option value={r}>{timeRangeLabels[r]}</option>
        {/each}
      </select>
    </label>
    <span class="hidden h-6 w-px bg-border md:block"></span>
    <Button variant="destructive" size="sm" onclick={requestClearLogs} disabled={ctrl.clearingLogs}>
      <Trash2 size={15} />
      {ctrl.clearingLogs ? 'Clearing...' : 'Clear logs'}
    </Button>
    <Button
      class="xl:ml-2"
      variant={prefs.detailPanelOpen ? 'secondary' : 'outline'}
      size="sm"
      onclick={() => ctrl.toggleDetailPanel()}
      aria-expanded={prefs.detailPanelOpen}
      aria-controls={prefs.detailPanelOpen ? LOGS_DETAIL_PANEL_ID : undefined}
    >
      {#if prefs.detailPanelOpen}
        <PanelRightClose size={15} />
      {:else}
        <PanelRightOpen size={15} />
      {/if}
      Log details
    </Button>
  {/snippet}

  {#snippet actionsCollapse({ expanded, toggle, ariaControls })}
    <Button
      variant="outline"
      size="icon"
      class="size-8"
      aria-expanded={expanded}
      aria-controls={ariaControls}
      aria-label={expanded ? 'Collapse log controls' : 'Expand log controls'}
      title={expanded ? 'Collapse log controls' : 'Expand log controls'}
      onclick={toggle}
    >
      {#if expanded}
        <ChevronUp size={16} />
      {:else}
        <ChevronDown size={16} />
      {/if}
    </Button>
  {/snippet}

  <AdminMasterDetail bind:detailOpen={prefs.detailPanelOpen} class="min-h-0 flex-1">
    {#snippet list()}
      <div class="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
        <LogsFiltersPanel
          {prefs}
          {ctrl}
          regionId={LOGS_FILTER_REGION_ID}
          regionHidden={prefs.controlsCollapsed}
        />

        {#if ctrl.error}
          <InlineDestructiveAlert message={ctrl.error} class="px-3 py-2 text-sm" />
        {:else if ctrl.pollError}
          <div
            class="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-sans text-sm text-amber-700 dark:text-amber-300"
          >
            {ctrl.pollError}
          </div>
        {/if}

        <LogsTablePanel
          {ctrl}
          detailPanelOpen={prefs.detailPanelOpen}
          bind:scroller={tableScroller}
          onSelectRow={selectRow}
          onOpenRowDetails={openRowDetails}
          onTableKeydown={(event) => ctrl.handleTableKeydown(event, () => tableScroller)}
          onFilterToMessage={ctrl.filterToMessage}
        />
      </div>
    {/snippet}
    {#snippet detail()}
      <LogsDetailPanel
        activeRow={ctrl.activeRow}
        onClose={() => (prefs.detailPanelOpen = false)}
        onNotify={notify}
      />
    {/snippet}
  </AdminMasterDetail>
</AdminPageHeader>

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

<ToastHost toast={toasts.toast} />
