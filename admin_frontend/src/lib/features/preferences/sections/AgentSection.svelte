<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { AGENT_MANIFEST } from '$lib/features/preferences/sections/agent-manifest';
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
  id={PREFERENCE_TAB_PANEL_IDS.agent}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.agent}
>
  {#if ctrl.sectionDescription('chat')}
    <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('chat')}</p>
  {/if}

  <!-- Cards + fields are data-driven from AGENT_MANIFEST (manifest rollout). -->
  {#if ctrl.draft}
    {#each AGENT_MANIFEST.cards as card (card.kind === 'card' ? card.id : card.component)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
