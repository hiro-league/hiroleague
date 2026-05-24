<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import type { GraphRunsPrimaryTabPreference } from '$lib/preferences/keys';
  import GraphRunsDetailPanel from './GraphRunsDetailPanel.svelte';
  import GraphRunsDialogs from './GraphRunsDialogs.svelte';
  import GraphRunsMemoriesPanel from './GraphRunsMemoriesPanel.svelte';
  import GraphRunsRunsPanel from './GraphRunsRunsPanel.svelte';
  import GraphRunsSubtabNav from './GraphRunsSubtabNav.svelte';
  import {
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_PRIMARY_TAB_IDS,
    GRAPH_RUNS_PRIMARY_TABLIST_LABEL,
    MEMORIES_TAB,
    RUNS_TAB
  } from './graph-runs-pure';
  import { createGraphRunsPageController } from './state/graph-runs-controller.svelte';

  const ctl = createGraphRunsPageController();
  onMount(ctl.mount);

  const pageTitle = $derived(ctl.primaryTab === MEMORIES_TAB ? 'Memories' : 'Graph runs');
  const pageSubtitle = $derived(
    ctl.primaryTab === MEMORIES_TAB
      ? 'Mem0 long-term store for the selected workspace (read-only).'
      : 'Recent agent turns with aggregate cost, latency, and drill-down timelines.'
  );

  const primaryTabDescriptors: readonly AdminTabDescriptor<GraphRunsPrimaryTabPreference>[] = [
    {
      id: RUNS_TAB,
      label: 'Graph runs',
      kind: 'pane',
      htmlId: GRAPH_RUNS_PRIMARY_TAB_IDS.runsWorkspace,
      ariaControls: `${GRAPH_RUNS_PANEL_IDS.runs} ${GRAPH_RUNS_PANEL_IDS.detail}`
    },
    {
      id: MEMORIES_TAB,
      label: 'Memories',
      kind: 'pane',
      htmlId: GRAPH_RUNS_PRIMARY_TAB_IDS.memories,
      ariaControls: GRAPH_RUNS_PANEL_IDS.memories
    }
  ];
</script>

<svelte:head>
  <title>{ctl.primaryTab === MEMORIES_TAB ? 'Memories' : 'Graph Runs'}</title>
</svelte:head>

<AdminPageHeader kicker="Operations" title={pageTitle} subtitle={pageSubtitle}>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel={GRAPH_RUNS_PRIMARY_TABLIST_LABEL}
      class="max-w-full flex-wrap"
      tabs={primaryTabDescriptors}
      active={ctl.primaryTab}
      onSelect={ctl.setPrimaryTab}
    />
  {/snippet}

  {#if ctl.activePane !== MEMORIES_TAB}
    <GraphRunsSubtabNav
      activePane={ctl.activePane}
      openRunIds={ctl.openRunIds}
      runDetailCardsExpanded={ctl.runDetailCardsExpanded}
      runTabDisplayLabel={ctl.runTabDisplayLabel}
      runTabTooltip={ctl.runTabTooltip}
      onShowRunsOnly={ctl.showRunsOnly}
      onOpenRunTab={(rid) => void ctl.openRunTab(rid)}
      onCloseRunTab={ctl.closeRunTab}
      onToggleRunDetailCards={ctl.toggleRunDetailCards}
      onRefresh={ctl.refreshMain}
    />
  {/if}

  <GraphRunsRunsPanel
    bind:filterCharacterId={ctl.filterCharacterId}
    bind:filterChannelId={ctl.filterChannelId}
    bind:filterStatus={ctl.filterStatus}
    bind:filterRunKind={ctl.filterRunKind}
    bind:previewSearch={ctl.previewSearch}
    hidden={ctl.activePane !== ctl.RUNS_TAB}
    error={ctl.error}
    visibleRows={ctl.visibleRows}
    openRunIds={ctl.openRunIds}
    previewSearchNeedle={ctl.previewSearchNeedle}
    charactersForFilterDropdown={ctl.charactersForFilterDropdown}
    channelsForFilterDropdown={ctl.channelsForFilterDropdown}
    statusesForFilterDropdown={ctl.statusesForFilterDropdown}
    characterMap={ctl.characterMap}
    channelById={ctl.channelById}
    onOpenRun={(runId) => void ctl.openRunTab(runId)}
  />

  <GraphRunsMemoriesPanel
    bind:memorySearch={ctl.memorySearch}
    bind:memoryFilterCharacterId={ctl.memoryFilterCharacterId}
    bind:memoryFilterChannelId={ctl.memoryFilterChannelId}
    bind:memoryFilterSource={ctl.memoryFilterSource}
    hidden={ctl.activePane !== ctl.MEMORIES_TAB}
    memoriesError={ctl.memoriesError}
    memoriesLoading={ctl.memoriesLoading}
    memoryEnabled={ctl.memoryEnabled}
    memoriesTotalCount={ctl.sortedMemoriesRows.length}
    visibleMemoriesRows={ctl.visibleMemoriesRows}
    charactersForFilterDropdown={ctl.charactersForFilterDropdown}
    channelsForMemoryFilterDropdown={ctl.channelsForMemoryFilterDropdown}
    sourcesForMemoryFilterDropdown={ctl.sourcesForMemoryFilterDropdown}
    characterMap={ctl.characterMap}
    channelById={ctl.channelById}
    memoryActionBusy={ctl.memoryActionBusy}
    onRequestClearAll={ctl.requestClearMemoriesConfirm}
    onRefreshMemories={() => void ctl.refreshMain()}
    onViewJson={ctl.showMemoryJsonRow}
    onDeleteRow={ctl.openDeleteMemoryDialog}
  />

  <GraphRunsDetailPanel
    activePane={ctl.activePane}
    runDetailCardsExpanded={ctl.runDetailCardsExpanded}
    activeRunAggregate={ctl.activeRunAggregate}
    langsmithUrlForActive={ctl.langsmithUrlForActive}
    runIdentitySource={ctl.runIdentitySource}
    titleCharacter={ctl.titleCharacter}
    runTitlePrimary={ctl.runTitlePrimary}
    runTitleSubtitle={ctl.runTitleSubtitle}
    runIdFirstCardDisplay={ctl.runIdFirstCardDisplay}
    toolbarElapsedLabel={ctl.toolbarElapsedLabel}
    toolbarTotalCostLabel={ctl.toolbarTotalCostLabel}
    timeline={ctl.timeline}
    selectedNodeRowId={ctl.selectedNodeRowId}
    nodeDetailRow={ctl.nodeDetailRow}
    headerFieldList={ctl.headerFieldList}
    nodeFieldList={ctl.nodeFieldList}
    nodeDetailFieldList={ctl.nodeDetailFieldList}
    onToggleNodeRow={ctl.toggleNodeRowSelection}
    onOpenNodeDetails={ctl.openNodeDetails}
    onCloseNodeDetails={ctl.closeNodeDetails}
  />
</AdminPageHeader>

<GraphRunsDialogs
  memoryJsonRow={ctl.memoryJsonRow}
  clearMemoriesConfirmOpen={ctl.clearMemoriesConfirmOpen}
  deleteMemoryTarget={ctl.deleteMemoryTarget}
  memoryActionBusy={ctl.memoryActionBusy}
  onCloseMemoryJson={ctl.closeMemoryJsonDialog}
  onCloseClearMemories={ctl.closeClearMemoriesDialog}
  onConfirmClearMemories={() => void ctl.confirmClearMemories()}
  onCloseDeleteMemory={ctl.closeDeleteMemoryDialog}
  onConfirmDeleteMemory={() => void ctl.confirmDeleteMemory()}
/>
