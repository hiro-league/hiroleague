<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Brain, Share2 } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { PageTab } from '$kit/ui/page-tabs.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import GraphPanel from '$kit/memory/graph/graph-panel.svelte';
  import { createGraphModel } from '$kit/memory/graph/state/create-graph-model.svelte';
  import MemoriesPanel from '$kit/memory/memories/memories-panel.svelte';
  import { MEMORIES_A11Y } from '$kit/memory/memories/shared/memories-a11y';
  import { ADMIN_PAGE_MAX_W_WIDE } from '$lib/styling/admin-tokens';
  import { createMemoriesPreferences } from '$lib/preferences/memories-preferences.svelte';
  import type { MemoriesTabPreference } from '$lib/preferences/keys';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import { adminMemorySource } from './state/memory-source';

  // The memories table and the entity graph are the UI kit's pieces (kit memory/), fed by the admin's
  // data source: its own API calls for the selected workspace, and the knowledge events stream for live
  // graph updates.
  const tabPrefs = createMemoriesPreferences();

  // The graph's live updates run at the page level so deltas keep accumulating even while the Memories
  // tab shows; the panel still owns rendering and its first load.
  let graphError = $state<string | null>(null);
  const graph = createGraphModel({ source: adminMemorySource, setError: (msg) => (graphError = msg) });

  onMount(() => {
    tabPrefs.initialize();
    return graph.connectEvents();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
  });

  const tabDescriptors: readonly PageTab<MemoriesTabPreference>[] = [
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
    <Notice message={graphError} />
  {/if}

  <!-- The table stays mounted while the Graph tab shows, so going back keeps its rows (it owns its controller). -->
  <MemoriesPanel source={adminMemorySource} hidden={tabPrefs.activeTab === 'graph'} />
  {#if tabPrefs.activeTab === 'graph'}
    <GraphPanel
      {graph}
      overlayOpen={chatOverlay.open}
      emptyMessage="No graph yet — build it from the Add tab (enable “build entity graph”)."
    />
  {/if}
</section>
