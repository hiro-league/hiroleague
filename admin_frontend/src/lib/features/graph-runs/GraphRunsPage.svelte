<script lang="ts">
  import { onMount } from 'svelte';
  /** Thin composition root: delegates orchestration to `state/graph-runs-controller.svelte.ts` (step #3). */
  import { createGraphRunsPageController } from './state/graph-runs-controller.svelte';
  /** Presentational slices (step #2). */
  import GraphRunsDetailPanel from './GraphRunsDetailPanel.svelte';
  import GraphRunsDialogs from './GraphRunsDialogs.svelte';
  import GraphRunsMemoriesPanel from './GraphRunsMemoriesPanel.svelte';
  import GraphRunsPageHeader from './GraphRunsPageHeader.svelte';
  import GraphRunsRunsPanel from './GraphRunsRunsPanel.svelte';

  const ctl = createGraphRunsPageController();
  onMount(ctl.mount);
</script>

<svelte:head>
  <title>{ctl.activePane === ctl.MEMORIES_TAB ? 'Memories' : 'Graph Runs'}</title>
</svelte:head>

<section class="graph-runs-page grid max-w-[1420px] gap-5 p-6">
  <GraphRunsPageHeader
    activePane={ctl.activePane}
    openRunIds={ctl.openRunIds}
    runDetailCardsExpanded={ctl.runDetailCardsExpanded}
    runTabDisplayLabel={ctl.runTabDisplayLabel}
    runTabTooltip={ctl.runTabTooltip}
    onActivatePrimaryRunsWorkspace={ctl.activateGraphRunsPrimaryTab}
    onShowRunsOnly={ctl.showRunsOnly}
    onShowMemories={ctl.showMemories}
    onOpenRunTab={(rid) => void ctl.openRunTab(rid)}
    onCloseRunTab={ctl.closeRunTab}
    onToggleRunDetailCards={ctl.toggleRunDetailCards}
    onRefresh={ctl.refreshMain}
  />

  <GraphRunsRunsPanel
    bind:filterCharacterId={ctl.filterCharacterId}
    bind:filterChannelId={ctl.filterChannelId}
    bind:filterStatus={ctl.filterStatus}
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
</section>

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

