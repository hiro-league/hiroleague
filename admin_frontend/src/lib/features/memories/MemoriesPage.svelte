<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import { ADMIN_PAGE_MAX_W_WIDE } from '$lib/styling/admin-tokens';
  // Memories is now its own page. It reuses the memory panel + dialogs that used
  // to live under the Graph Runs page (they are already memory-only); relocating
  // them into this slice is a deferred "enhance later" cleanup.
  import GraphRunsMemoriesPanel from '$lib/features/graph-runs/GraphRunsMemoriesPanel.svelte';
  import GraphRunsDialogs from '$lib/features/graph-runs/GraphRunsDialogs.svelte';
  import { createMemoriesPageController } from './state/memories-controller.svelte';

  const ctl = createMemoriesPageController();
  onMount(ctl.mount);
</script>

<svelte:head>
  <title>Memories - Hiro Admin</title>
</svelte:head>

<AdminPageHeader
  sticky
  wrapperClass={ADMIN_PAGE_MAX_W_WIDE}
  kicker="Operations"
  title="Memories"
  subtitle="Long-term agent memory (Graphiti facts) for the selected workspace."
>
  <GraphRunsMemoriesPanel
    bind:memorySearch={ctl.memorySearch}
    bind:memoryFilterCharacterId={ctl.memoryFilterCharacterId}
    bind:memoryFilterSource={ctl.memoryFilterSource}
    bind:memoryFilterDateFrom={ctl.memoryFilterDateFrom}
    bind:memoryFilterDateTo={ctl.memoryFilterDateTo}
    hidden={false}
    memoriesError={ctl.memoriesError}
    memoriesLoading={ctl.memoriesLoading}
    memoryEnabled={ctl.memoryEnabled}
    memoriesTotalCount={ctl.sortedMemoriesRows.length}
    visibleMemoriesRows={ctl.visibleMemoriesRows}
    charactersForFilterDropdown={ctl.charactersForFilterDropdown}
    sourcesForMemoryFilterDropdown={ctl.sourcesForMemoryFilterDropdown}
    characterMap={ctl.characterMap}
    channelById={ctl.channelById}
    memoryActionBusy={ctl.memoryActionBusy}
    onRequestClearAll={ctl.requestClearMemoriesConfirm}
    onRefreshMemories={() => void ctl.refreshMemories()}
    onViewJson={ctl.showMemoryJsonRow}
    onDeleteRow={ctl.openDeleteMemoryDialog}
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
