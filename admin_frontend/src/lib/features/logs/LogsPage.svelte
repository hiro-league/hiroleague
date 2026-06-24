<script lang="ts">
  import { onMount } from 'svelte';
  import { afterNavigate } from '$app/navigation';
  import { FolderOpen } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import { ADMIN_HEADER_INTRO, ADMIN_PAGE_MAX_W_WIDE } from '$lib/styling/admin-tokens';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import { cn } from '$lib/utils';
  import { createLogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import { createLogsTabPreferences } from '$lib/preferences/logs-tab-preferences.svelte';
  import { createLogsPageController } from './state/logs-controller.svelte';
  import LogsPanel from './LogsPanel.svelte';
  // Graph runs is the Logs page's second tab — its panels/subnav are reused here
  // and driven by their own (runs-only) controller. Memories moved to its own page.
  import GraphRunsRunsPanel from '$lib/features/graph-runs/GraphRunsRunsPanel.svelte';
  import GraphRunsDetailPanel from '$lib/features/graph-runs/GraphRunsDetailPanel.svelte';
  import GraphRunsSubtabNav from '$lib/features/graph-runs/GraphRunsSubtabNav.svelte';
  import { createGraphRunsPageController } from '$lib/features/graph-runs/state/graph-runs-controller.svelte';
  import { LOGS_TAB_DESCRIPTORS } from './shared/logs-page-config';

  // Logs feed (first tab) — controller + filter prefs owned here so the shared
  // header chrome (folder button, counts, collapse chevron) can read them.
  const prefs = createLogsPreferences();
  const logsCtrl = createLogsPageController({ prefs });
  // Primary `?tab=logs|runs` pill.
  const tabPrefs = createLogsTabPreferences();

  const toasts = createToastNotifier();
  const notify = toasts.notify;
  // Graph runs (second tab) — runs-only controller. `notify` drives the eval-detail bridge's
  // load/trace toasts.
  const runsCtrl = createGraphRunsPageController(notify);

  const isRunsTab = $derived(tabPrefs.activeTab === 'runs');
  const pageTitle = $derived(isRunsTab ? 'Graph runs' : 'Logs');

  onMount(() => {
    tabPrefs.initialize();
    // The runs ledger controller lives at the page level so its state survives
    // tab switches; the logs feed controller starts inside LogsPanel's lifecycle.
    return runsCtrl.mount();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
  });
</script>

<svelte:head>
  <title>{pageTitle} - Hiro Admin</title>
</svelte:head>

<AdminPageHeader
  sticky
  kicker="Operations"
  title={pageTitle}
  wrapperClass={ADMIN_PAGE_MAX_W_WIDE}
>
  {#snippet titleAdornment()}
    {#if !isRunsTab}
      <button
        class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-40"
        type="button"
        disabled={!logsCtrl.layout?.log_dir?.trim()}
        onclick={() => void logsCtrl.openLogsFolder(notify)}
        title={logsCtrl.layout?.log_dir?.trim()
          ? `Open logs folder: ${logsCtrl.layout.log_dir.trim()}`
          : 'Open logs folder'}
        aria-label={logsCtrl.layout?.log_dir?.trim()
          ? `Open logs folder: ${logsCtrl.layout.log_dir.trim()}`
          : 'Open logs folder'}
      >
        <FolderOpen size={13} />
      </button>
    {/if}
  {/snippet}

  {#snippet subtitleSlot()}
    {#if isRunsTab}
      <p class={cn(ADMIN_HEADER_INTRO, 'mt-1 font-sans text-xs')}>
        Recent agent turns with aggregate cost, latency, and drill-down timelines.
      </p>
    {:else}
      <p class={cn(ADMIN_HEADER_INTRO, 'mt-1 font-sans text-xs')}>
        {logsCtrl.visibleRows.length} visible / {logsCtrl.rows.length} loaded
        {#if logsCtrl.searchBusy}
          <span class="ml-2 text-primary">Searching...</span>
        {:else if logsCtrl.isSearchMode || logsCtrl.hasScopeFilters}
          <span class="ml-2 text-primary">Filtered</span>
        {/if}
      </p>
    {/if}
  {/snippet}

  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Logs sections"
      class="max-w-full flex-wrap"
      tabs={LOGS_TAB_DESCRIPTORS}
      active={tabPrefs.activeTab}
      onSelect={(id) => {
        void tabPrefs.setActiveTab(id);
      }}
    />
  {/snippet}

  {#snippet subnav()}
    {#if isRunsTab}
      <GraphRunsSubtabNav
        activePane={runsCtrl.activePane}
        openRunIds={runsCtrl.openRunIds}
        runDetailCardsExpanded={runsCtrl.runDetailCardsExpanded}
        runTabDisplayLabel={runsCtrl.runTabDisplayLabel}
        runTabTooltip={runsCtrl.runTabTooltip}
        onShowRunsOnly={runsCtrl.showRunsOnly}
        onOpenRunTab={(rid) => void runsCtrl.openRunTab(rid)}
        onCloseRunTab={runsCtrl.closeRunTab}
        onToggleRunDetailCards={runsCtrl.toggleRunDetailCards}
        onRefresh={runsCtrl.refreshMain}
      />
    {/if}
  {/snippet}

  {#if isRunsTab}
    <GraphRunsRunsPanel
      bind:filterCharacterId={runsCtrl.filterCharacterId}
      bind:filterChannelId={runsCtrl.filterChannelId}
      bind:filterStatus={runsCtrl.filterStatus}
      bind:filterRunKind={runsCtrl.filterRunKind}
      bind:previewSearch={runsCtrl.previewSearch}
      hidden={runsCtrl.activePane !== runsCtrl.RUNS_TAB}
      error={runsCtrl.error}
      visibleRows={runsCtrl.visibleRows}
      openRunIds={runsCtrl.openRunIds}
      charactersForFilterDropdown={runsCtrl.charactersForFilterDropdown}
      channelsForFilterDropdown={runsCtrl.channelsForFilterDropdown}
      statusesForFilterDropdown={runsCtrl.statusesForFilterDropdown}
      characterMap={runsCtrl.characterMap}
      channelById={runsCtrl.channelById}
      hasMoreRuns={runsCtrl.hasMoreRuns}
      loadingMoreRuns={runsCtrl.loadingMoreRuns}
      onOpenRun={(runId) => void runsCtrl.openRunTab(runId)}
      onLoadMore={() => void runsCtrl.loadMoreRuns()}
    />

    <GraphRunsDetailPanel
      activePane={runsCtrl.activePane}
      runDetailCardsExpanded={runsCtrl.runDetailCardsExpanded}
      activeRunAggregate={runsCtrl.activeRunAggregate}
      langsmithUrlForActive={runsCtrl.langsmithUrlForActive}
      runIdentitySource={runsCtrl.runIdentitySource}
      titleCharacter={runsCtrl.titleCharacter}
      runTitlePrimary={runsCtrl.runTitlePrimary}
      runTitleSubtitle={runsCtrl.runTitleSubtitle}
      runIdFirstCardDisplay={runsCtrl.runIdFirstCardDisplay}
      toolbarElapsedLabel={runsCtrl.toolbarElapsedLabel}
      toolbarTotalCostLabel={runsCtrl.toolbarTotalCostLabel}
      timeline={runsCtrl.timeline}
      selectedNodeRowId={runsCtrl.selectedNodeRowId}
      nodeDetailRow={runsCtrl.nodeDetailRow}
      headerFieldList={runsCtrl.headerFieldList}
      nodeFieldList={runsCtrl.nodeFieldList}
      nodeDetailFieldList={runsCtrl.nodeDetailFieldList}
      traceStepIds={runsCtrl.traces.retrievalTraceStepIds}
      activeRetrievalTrace={runsCtrl.traces.activeRetrievalTrace}
      ingestTraceStepIds={runsCtrl.traces.ingestTraceStepIds}
      activeIngestTrace={runsCtrl.traces.activeIngestTrace}
      onToggleNodeRow={runsCtrl.toggleNodeRowSelection}
      onOpenNodeDetails={runsCtrl.openNodeDetails}
      onCloseNodeDetails={runsCtrl.closeNodeDetails}
      onOpenRetrievalTrace={runsCtrl.traces.openRetrievalTrace}
      onCloseRetrievalTrace={runsCtrl.traces.closeRetrievalTrace}
      onOpenIngestTrace={runsCtrl.traces.openIngestTrace}
      onCloseIngestTrace={runsCtrl.traces.closeIngestTrace}
      ingestTraceHasPrev={runsCtrl.traces.ingestTraceHasPrev}
      ingestTraceHasNext={runsCtrl.traces.ingestTraceHasNext}
      ingestTraceNavIndex={runsCtrl.traces.ingestTraceNavIndex}
      ingestTraceNavTotal={runsCtrl.traces.ingestTraceNavTotal}
      onPrevIngestTrace={runsCtrl.traces.prevIngestTrace}
      onNextIngestTrace={runsCtrl.traces.nextIngestTrace}
      activeEvalRow={runsCtrl.activeEvalRow}
      evalRowLegColumns={runsCtrl.evalRowLegColumns}
      evalRowTraces={runsCtrl.evalRowTraces}
      onOpenEvalRow={(row) => void runsCtrl.openEvalRowForNode(row)}
      onCloseEvalRow={runsCtrl.closeEvalRow}
    />
  {:else}
    <LogsPanel ctrl={logsCtrl} {prefs} {notify} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
