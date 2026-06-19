<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import KnowledgeAnsweringCard from '$lib/features/preferences/sections/knowledge/KnowledgeAnsweringCard.svelte';
  import KnowledgeEmbeddingChunkingCard from '$lib/features/preferences/sections/knowledge/KnowledgeEmbeddingChunkingCard.svelte';
  import KnowledgeGraphBackendCard from '$lib/features/preferences/sections/knowledge/KnowledgeGraphBackendCard.svelte';
  import KnowledgeRerankerCard from '$lib/features/preferences/sections/knowledge/KnowledgeRerankerCard.svelte';
  import KnowledgeRetrievalCard from '$lib/features/preferences/sections/knowledge/KnowledgeRetrievalCard.svelte';
  import KnowledgeRewriteCard from '$lib/features/preferences/sections/knowledge/KnowledgeRewriteCard.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';
  import KnowledgeBrowseLink from '$lib/features/preferences/widgets/KnowledgeBrowseLink.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.knowledge}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.knowledge}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    {#if ctrl.sectionDescription('knowledge')}
      <p class="min-w-0 flex-1 text-sm text-muted-foreground">{ctrl.sectionDescription('knowledge')}</p>
    {/if}
    <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
      <KnowledgeBrowseLink busy={ctrl.busy} />
      <ActiveProvidersLink busy={ctrl.busy} />
    </div>
  </div>

  {#if ctrl.draft}
    <KnowledgeEmbeddingChunkingCard {ctrl} />
    <KnowledgeRetrievalCard {ctrl} />
    <KnowledgeRerankerCard {ctrl} />
    <KnowledgeRewriteCard {ctrl} />
    <KnowledgeAnsweringCard {ctrl} />
    <KnowledgeGraphBackendCard {ctrl} />
  {/if}
</div>
