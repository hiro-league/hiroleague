<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { KNOWLEDGE_MANIFEST } from '$lib/features/preferences/sections/knowledge/knowledge-manifest';
  import PrefManifestCard from '$lib/features/preferences/widgets/manifest/PrefManifestCard.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import KnowledgeBrowseLink from '$lib/features/preferences/widgets/KnowledgeBrowseLink.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.knowledge}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.knowledge}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    {#if ctrl.sectionDescription('knowledge')}
      <p class="min-w-0 flex-1 text-sm text-muted-foreground">
        {ctrl.sectionDescription('knowledge')}
      </p>
    {/if}
    <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
      <KnowledgeBrowseLink busy={ctrl.busy} />
    </div>
  </div>

  <!-- Cards + fields are data-driven from KNOWLEDGE_MANIFEST (manifest rollout). -->
  {#if ctrl.draft}
    {#each KNOWLEDGE_MANIFEST.cards as card (card.id)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
