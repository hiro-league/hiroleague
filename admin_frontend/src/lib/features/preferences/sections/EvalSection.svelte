<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { EVAL_MANIFEST } from '$lib/features/preferences/sections/eval/eval-manifest';
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
  id={PREFERENCE_TAB_PANEL_IDS.eval}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.eval}
>
  <p class="text-sm text-muted-foreground">
    Settings for the evaluation harness — the answer and judge models the eval runs use, and the
    memory-eval answer/judge prompt libraries. Eval-only; these don't affect production chat,
    knowledge, or memory.
  </p>

  <!-- Cards + fields are data-driven from EVAL_MANIFEST (manifest rollout). -->
  {#if ctrl.draft}
    {#each EVAL_MANIFEST.cards as card (card.id)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
