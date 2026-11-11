<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Brain, Share2 } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { ADMIN_PAGE_MAX_W_WIDE } from '$lib/styling/admin-tokens';
  import { createMemoriesPreferences } from '$lib/preferences/memories-preferences.svelte';
  import type { MemoriesTabPreference } from '$lib/preferences/keys';
  import MemoriesPanel from './MemoriesPanel.svelte';
  import MemoriesDialogs from './MemoriesDialogs.svelte';
  import { MEMORIES_A11Y } from './shared/memories-a11y';
  // The entity-graph viz moved here from the Knowledge page as a second tab. The
  // component still lives under features/knowledge/graph (it renders the
  // knowledge entity graph); the Memories controller owns its model + live SSE.
  import KnowledgeGraphPanel from '$lib/features/knowledge/graph/KnowledgeGraphPanel.svelte';
  import { createKnowledgeGraphModel } from '$lib/features/knowledge/state/knowledge-graph.svelte';
  import { createMemoriesPageController } from './state/memories-controller.svelte';

  const tabPrefs = createMemoriesPreferences();
  const ctl = createMemoriesPageController();

  // The entity-graph viz (second tab) is a self-contained knowledge model owned here, not by the
  // memories controller. Its live SSE runs at the page level so deltas keep accumulating even
  // while the user is on the Memories tab; the panel still owns rendering + its initial load.
  let graphError = $state<string | null>(null);
  const graph = createKnowledgeGraphModel({ setError: (msg) => (graphError = msg) });

  onMount(() => {
    tabPrefs.initialize();
    ctl.mount();
    return graph.connectEvents();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
  });

  const tabDescriptors: readonly AdminTabDescriptor<MemoriesTabPreference>[] = [
    {
      id: 'memories',
      label: 'Memories',
      kind: 'pane',
      icon: Brain,
      htmlId: MEMORIES_A11Y.memoriesTab,
      ariaControls: MEMORIES_A11Y.memoriesPanel
    },
    { id: 'graph', label: 'Graph', kind: 'pane', icon: Share2 }
  ];
</script>

<svelte:head>
  <title>Memories - Hiro Admin</title>
</svelte:head>

<section class={ADMIN_PAGE_MAX_W_WIDE}>
  <PageHeader title="Memories" description="Long-term agent memory (Graphiti facts) for the selected workspace.">
    {#snippet tabs()}
    <PageTabs
      label="Memories sections"
      tabs={tabDescriptors}
      value={tabPrefs.activeTab}
      onchange={(id) => {
        void tabPrefs.setActiveTab(id);
      }}
    />
    {/snippet}
  </PageHeader>
  

  {#if tabPrefs.activeTab === 'graph' && graphError}
    <InlineDestructiveAlert message={graphError} />
  {/if}

  {#if tabPrefs.activeTab === 'graph'}
    <KnowledgeGraphPanel {graph} />
  {:else}
    <MemoriesPanel
      filters={ctl.filters}
      setFilter={ctl.setFilter}
      sort={ctl.sort}
      hidden={false}
      memoriesError={ctl.memoriesError}
      memoriesLoading={ctl.memoriesLoading}
      memoryEnabled={ctl.memoryEnabled}
      memoriesTotalCount={ctl.sortedMemoriesRows.length}
      visibleMemoriesRows={ctl.visibleMemoriesRows}
      charactersForFilterDropdown={ctl.charactersForFilterDropdown}
      groupsForMemoryFilterDropdown={ctl.memoryGroupsForFilterDropdown}
      sourcesForMemoryFilterDropdown={ctl.sourcesForMemoryFilterDropdown}
      characterMap={ctl.characterMap}
      channelById={ctl.channelById}
      groupLabelById={ctl.memoryGroupLabelById}
      memoryActionBusy={ctl.memoryActionBusy}
      canClearMemories={ctl.canClearMemories}
      clearableMemoryCount={ctl.clearableMemoryCount}
      onRequestClearMemories={ctl.requestClearMemoriesConfirm}
      onRequestClearGroup={ctl.requestClearGroupConfirm}
      onRefreshMemories={() => void ctl.refreshMemories()}
      onViewJson={ctl.showMemoryJsonRow}
      onViewProvenance={ctl.showMemoryProvenance}
    />
  {/if}
</section>

<MemoriesDialogs
  memoryJsonRow={ctl.memoryJsonRow}
  memoryProvenanceRow={ctl.memoryProvenanceRow}
  memoryProvenanceChunks={ctl.memoryProvenanceChunks}
  memoryProvenanceLoading={ctl.memoryProvenanceLoading}
  memoryProvenanceError={ctl.memoryProvenanceError}
  clearMemoriesConfirmOpen={ctl.clearMemoriesConfirmOpen}
  clearGroupConfirmOpen={ctl.clearGroupConfirmOpen}
  clearableMemoryCount={ctl.clearableMemoryCount}
  selectedGroupLabel={ctl.selectedGroupLabel}
  memoryActionBusy={ctl.memoryActionBusy}
  onCloseMemoryJson={ctl.closeMemoryJsonDialog}
  onCloseProvenance={ctl.closeMemoryProvenance}
  onCloseClearMemories={ctl.closeClearMemoriesDialog}
  onConfirmClearMemories={() => void ctl.confirmClearMemories()}
  onCloseClearGroup={ctl.closeClearGroupDialog}
  onConfirmClearGroup={() => void ctl.confirmClearGroup()}
/>
