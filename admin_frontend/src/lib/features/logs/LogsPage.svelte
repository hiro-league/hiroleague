<script lang="ts">
  import { onMount } from 'svelte';
  import { afterNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import { FolderOpen } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import { ADMIN_PAGE_MAX_W_WIDE } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
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
  import AiUsagePanel from '$lib/features/ai-usage/AiUsagePanel.svelte';
  // Logging and tracing plan, phase 6b: the stories, each drawn by its kind
  import StoriesPanel from './one-view/StoriesPanel.svelte';
  import StoryDialog from './one-view/StoryDialog.svelte';
  import StoriesToolbar from './one-view/StoriesToolbar.svelte';
  import { StoriesFilters } from './one-view/stories-filters.svelte';

  // Logs feed (first tab) — controller + filter prefs owned here so the shared
  // header chrome (folder button, counts, collapse chevron) can read them.
  const prefs = createLogsPreferences();
  const logsCtrl = createLogsPageController({ prefs });
  // Primary `?tab=logs|runs` pill.
  const tabPrefs = createLogsTabPreferences();

  const notify = toast.show;
  // Graph runs (second tab) — runs-only controller. `notify` drives the recall detail's
  // load/trace toasts.
  const runsCtrl = createGraphRunsPageController(notify);

  const isRunsTab = $derived(tabPrefs.activeTab === 'runs');
  const isUsageTab = $derived(tabPrefs.activeTab === 'usage'); // Phase 7b: AI usage
  const isStoriesTab = $derived(tabPrefs.activeTab === 'stories');
  const pageTitle = $derived(isRunsTab ? 'Graph runs' : isUsageTab ? 'AI usage' : isStoriesTab ? 'Stories' : 'Logs');

  // A story opens over the page (Logs or Stories) from `?story=<id>`, so its link can be shared; on Graph runs the
  // same param opens that story's run instead
  const storiesFilters = new StoriesFilters();
  const openStoryId = $derived(isRunsTab ? '' : (page.url.searchParams.get('story')?.trim() ?? ''));
  function setStoryParam(id: string) {
    const url = new URL(page.url);
    if (id) url.searchParams.set('story', id);
    else url.searchParams.delete('story');
    void goto(url, { noScroll: true, keepFocus: true });
  }

  onMount(() => {
    tabPrefs.initialize();
    // The runs ledger controller lives at the page level so its state survives
    // tab switches; the logs feed controller starts inside LogsPanel's lifecycle.
    return runsCtrl.mount();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
    // `?tab=runs&story=<id>` (a log line's "Open its graph run"): the run that story's ledger rows name
    const story = page.url.searchParams.get('story')?.trim();
    if (tabPrefs.activeTab === 'runs' && story) void runsCtrl.openStory(story);
  });
</script>

{#snippet storiesBar()}
  <StoriesToolbar filters={storiesFilters} />
{/snippet}

{#snippet runsNav()}
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
{/snippet}

<svelte:head>
  <title>{pageTitle} - Hiro Admin</title>
</svelte:head>

<section class={ADMIN_PAGE_MAX_W_WIDE}>
  <PageHeader title={pageTitle} children={isRunsTab ? runsNav : isStoriesTab ? storiesBar : undefined}>
    {#snippet adornment()}
    {#if !isRunsTab && !isUsageTab && !isStoriesTab}
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
    {#snippet details()}
    {#if isRunsTab}
      <p class={'mt-1 font-sans text-xs text-muted-foreground'}>
        Recent agent turns with aggregate cost, latency, and drill-down timelines.
      </p>
    {:else if isUsageTab}
      <p class={'mt-1 font-sans text-xs text-muted-foreground'}>
        What every paid AI call costs (questions, speech, transcription, images, embeddings): the extensions' and Hiro's own jobs, by the hour.
      </p>
    {:else if !isStoriesTab}
      <p class={'mt-1 font-sans text-xs text-muted-foreground'}>
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
    <PageTabs
      label="Logs sections"
      class="max-w-full flex-wrap"
      tabs={LOGS_TAB_DESCRIPTORS}
      value={tabPrefs.activeTab}
      onchange={(id) => {
        void tabPrefs.setActiveTab(id);
      }}
    />
    {/snippet}
  </PageHeader>
  

  

  

  

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
      activeRecall={runsCtrl.activeRecall}
      recallTraces={runsCtrl.recallTraces}
      onOpenRetrievalLoop={(row) => void runsCtrl.openRetrievalLoopForNode(row)}
      onCloseRecall={runsCtrl.closeRecall}
    />
  {:else if isUsageTab}
    <AiUsagePanel />
  {:else if isStoriesTab}
    <StoriesPanel filters={storiesFilters} onOpenStory={setStoryParam} />
  {:else}
    <LogsPanel ctrl={logsCtrl} {prefs} {notify} onOpenStory={setStoryParam} />
  {/if}

  {#if openStoryId}
    <StoryDialog storyId={openStoryId} onClose={() => setStoryParam('')} {notify} />
  {/if}
</section>

