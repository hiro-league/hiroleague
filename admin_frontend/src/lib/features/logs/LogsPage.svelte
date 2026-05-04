<script lang="ts">
  import { onMount, tick } from 'svelte';
  import type { LogTimeRange } from '$lib/api/logs';
  import { cn } from '$lib/utils';
  import LogsDetailPanel from './LogsDetailPanel.svelte';
  import LogsFiltersPanel from './LogsFiltersPanel.svelte';
  import LogsPageHeader from './LogsPageHeader.svelte';
  import LogsTablePanel from './LogsTablePanel.svelte';
  import { createLogsPageController } from './state/logs-controller.svelte';
  import { createLogsPreferences } from './state/logs-preferences.svelte';
  import { LOGS_FILTER_REGION_ID } from './shared/logs-a11y';
  import { setupLogsPageRuntime } from './shared/logs-page-lifecycle';
  import type { RenderLogRow } from './shared/logs-ui';

  const prefs = createLogsPreferences();
  const ctrl = createLogsPageController({ prefs });

  let autoScroll = $state(true);
  let tableScroller = $state<HTMLDivElement | null>(null);

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

  function toggleLastSessionOnly() {
    prefs.lastSessionOnly = !prefs.lastSessionOnly;
    void ctrl.reloadLiveTail();
  }

  function onLogTimeRangeChange(value: LogTimeRange) {
    prefs.logTimeRange = value;
    void ctrl.reloadLiveTail();
  }

  onMount(() => setupLogsPageRuntime({ prefs, ctrl }));
</script>

<section class="logs-page flex h-full min-h-0 flex-col gap-4 overflow-hidden">
  <LogsPageHeader
    searchText={prefs.searchText}
    onSearchInput={ctrl.onSearchInput}
    onClearSearch={() => void ctrl.clearSearch()}
    sortOrder={prefs.sortOrder}
    onToggleSort={() => prefs.toggleSort()}
    paused={prefs.paused}
    onTogglePause={() => prefs.togglePause()}
    blocksLiveTail={ctrl.blocksLiveTail}
    onClearAllFilters={() => void ctrl.clearAllFilters()}
    {autoScroll}
    onToggleAutoScroll={() => (autoScroll = !autoScroll)}
    lastSessionOnly={prefs.lastSessionOnly}
    onToggleLastSessionOnly={toggleLastSessionOnly}
    logTimeRange={prefs.logTimeRange}
    onLogTimeRangeChange={onLogTimeRangeChange}
    detailPanelOpen={prefs.detailPanelOpen}
    onToggleDetailPanel={() => ctrl.toggleDetailPanel()}
    controlsCollapsed={prefs.controlsCollapsed}
    onToggleControlsCollapsed={() => prefs.toggleControlsCollapsed()}
    filtersRegionId={LOGS_FILTER_REGION_ID}
    visibleCount={ctrl.visibleRows.length}
    loadedCount={ctrl.rows.length}
    searchBusy={ctrl.searchBusy}
    filtered={ctrl.isSearchMode || ctrl.hasScopeFilters}
  />

  <div
    class={cn(
      'grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden',
      prefs.detailPanelOpen &&
        'min-[1180px]:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]'
    )}
  >
    <div class="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
      <LogsFiltersPanel
        {prefs}
        {ctrl}
        regionId={LOGS_FILTER_REGION_ID}
        regionHidden={prefs.controlsCollapsed}
      />

      {#if ctrl.error}
        <div
          class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive"
        >
          {ctrl.error}
        </div>
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

    {#if prefs.detailPanelOpen}
      <LogsDetailPanel activeRow={ctrl.activeRow} onClose={() => (prefs.detailPanelOpen = false)} />
    {/if}
  </div>
</section>

<style>
  /* Class name must match LOGS_NO_DOCUMENT_SCROLL_CLASS in shared/logs-page-lifecycle.ts */
  :global(html.admin-logs-no-document-scroll),
  :global(html.admin-logs-no-document-scroll body) {
    overflow: hidden;
  }
</style>
