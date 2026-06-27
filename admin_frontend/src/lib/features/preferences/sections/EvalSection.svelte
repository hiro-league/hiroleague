<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import EvalJudgePromptCard from '$lib/features/preferences/sections/eval/EvalJudgePromptCard.svelte';
  import EvalMemAnswerPromptCard from '$lib/features/preferences/sections/eval/EvalMemAnswerPromptCard.svelte';
  import EvalModelsCard from '$lib/features/preferences/sections/eval/EvalModelsCard.svelte';
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
  id={PREFERENCE_TAB_PANEL_IDS.eval}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.eval}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <p class="min-w-0 flex-1 text-sm text-muted-foreground">
      Settings for the evaluation harness — the answer and judge models the eval runs use, and the
      memory-eval answer/judge prompt libraries. Eval-only; these don't affect production chat,
      knowledge, or memory.
    </p>
    <ActiveProvidersLink busy={ctrl.busy} />
  </div>

  {#if ctrl.draft}
    <EvalModelsCard {ctrl} />
    <EvalMemAnswerPromptCard {ctrl} />
    <EvalJudgePromptCard {ctrl} />
  {/if}
</div>
