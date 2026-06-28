<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import GraphRetrievalAgentCard from '$lib/features/preferences/sections/graph-engine/GraphRetrievalAgentCard.svelte';
  import GraphRetrievalAgentModelCard from '$lib/features/preferences/sections/graph-engine/GraphRetrievalAgentModelCard.svelte';
  import GraphExtractionCard from '$lib/features/preferences/sections/graph-engine/GraphExtractionCard.svelte';
  import GraphRerankerCard from '$lib/features/preferences/sections/graph-engine/GraphRerankerCard.svelte';
  import GraphSearchIndexingCard from '$lib/features/preferences/sections/graph-engine/GraphSearchIndexingCard.svelte';
  import GraphViewCard from '$lib/features/preferences/sections/graph-engine/GraphViewCard.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS['graph-engine']}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS['graph-engine']}
>
  <p class="text-sm text-muted-foreground">
    One Graphiti temporal-graph engine, shared by <span class="font-medium">Agent Memory</span> and
    <span class="font-medium">Knowledge</span> — these models and graph-search settings apply to
    both. (Whether Knowledge <em>retrieval</em> uses the graph is the "Graph backend" toggle on the
    Knowledge tab.) Changing the graph embedder re-indexes all graph data.
  </p>

  {#if ctrl.draft}
    <GraphExtractionCard {ctrl} />
    <GraphSearchIndexingCard {ctrl} />
    <GraphRerankerCard {ctrl} />
    <GraphRetrievalAgentModelCard {ctrl} />
    <GraphRetrievalAgentCard {ctrl} />
    <GraphViewCard {ctrl} />
  {/if}
</div>
