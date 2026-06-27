<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import GraphEvalRetrievalAgentPromptCard from '$lib/features/preferences/sections/graph-engine/GraphEvalRetrievalAgentPromptCard.svelte';
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
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';

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
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <p class="min-w-0 flex-1 text-sm text-muted-foreground">
      One Graphiti temporal-graph engine, shared by <span class="font-medium">Agent Memory</span> and
      <span class="font-medium">Knowledge</span> — these models and graph-search settings apply to
      both. (Whether Knowledge <em>retrieval</em> uses the graph is the "Graph backend" toggle on the
      Knowledge tab.) Changing the graph embedder re-indexes all graph data.
    </p>
    <ActiveProvidersLink busy={ctrl.busy} />
  </div>

  {#if ctrl.draft}
    <GraphExtractionCard {ctrl} />
    <GraphSearchIndexingCard {ctrl} />
    <GraphRerankerCard {ctrl} />
    <GraphRetrievalAgentCard {ctrl} />
    <GraphRetrievalAgentModelCard {ctrl} />
    <GraphEvalRetrievalAgentPromptCard {ctrl} />
    <GraphViewCard {ctrl} />
  {/if}
</div>
