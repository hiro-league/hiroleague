<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { MODELS_MANIFEST } from '$lib/features/preferences/sections/models-manifest';
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
  id={PREFERENCE_TAB_PANEL_IDS.models}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.models}
>
  {#if ctrl.sectionDescription('llm')}
    <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('llm')}</p>
  {/if}

  <!-- Cards + fields are data-driven from MODELS_MANIFEST (manifest rollout). -->
  {#if ctrl.draft}
    {#each MODELS_MANIFEST.cards as card (card.id)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
