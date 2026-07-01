<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { GRAPH_ENGINE_MANIFEST } from '$lib/features/preferences/sections/graph-engine/graph-engine-manifest';
  import PrefManifestCard from '$lib/features/preferences/widgets/manifest/PrefManifestCard.svelte';
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
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS['graph-engine']}
>
  <p class="text-sm text-muted-foreground">
    One Graphiti temporal-graph engine, shared by <span class="font-medium">Agent Memory</span> and
    <span class="font-medium">Knowledge</span> — these models and graph-search settings apply to
    both. (Whether Knowledge <em>retrieval</em> uses the graph is the "Graph backend" toggle on the
    Knowledge tab.) Changing the graph embedder re-indexes all graph data.
  </p>

  <!-- Cards + fields are data-driven from GRAPH_ENGINE_MANIFEST (Tier-2.1). Order, sections, and the
       search index all derive from the same manifest — see graph-engine-manifest.ts. -->
  {#if ctrl.draft}
    {#each GRAPH_ENGINE_MANIFEST.cards as card (card.id)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
