<script lang="ts">
  /**
   * Renders one `PrefCardSpec`: a data-driven `card` (a `PrefSectionCard` wrapping manifest fields)
   * or a `customCard` (a bespoke card component resolved by the registry below — kept whole when its
   * logic, e.g. cross-field validation or gating, is too card-specific to express as field specs).
   */
  import type { Component } from 'svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import type { CustomCardKey, PrefCardSpec } from './manifest-types';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import PrefFieldRenderer from './PrefFieldRenderer.svelte';
  import GraphRerankerCard from '$lib/features/preferences/sections/graph-engine/GraphRerankerCard.svelte';
  import GraphRetrievalAgentCard from '$lib/features/preferences/sections/graph-engine/GraphRetrievalAgentCard.svelte';

  let { ctrl, card }: { ctrl: PreferencesController; card: PrefCardSpec } = $props();

  const CUSTOM_CARDS: Record<CustomCardKey, Component<{ ctrl: PreferencesController }>> = {
    graphReranker: GraphRerankerCard,
    graphRetrievalAgent: GraphRetrievalAgentCard
  };
</script>

{#if card.kind === 'card'}
  <PrefSectionCard
    title={card.title}
    description={card.descriptionOf ? card.descriptionOf(ctrl) : card.description}
    collapsible={card.collapsible ?? false}
    bodyId={card.bodyId}
  >
    {#each card.body as field, i (i)}
      <PrefFieldRenderer {ctrl} spec={field} />
    {/each}
  </PrefSectionCard>
{:else}
  {@const CustomCard = CUSTOM_CARDS[card.component]}
  <CustomCard {ctrl} />
{/if}
