<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Evaluation Models"
    description="Models + profiles the eval harness uses — the answer step (memory track) and the judge (both tracks). Eval-only; the knowledge track answers with the production pipeline, not the answer model here."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.evalModels}
  >
    <PrefFieldGrid>
      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.eval.answer_model"
          labelled
          embedded
          label="Eval answer model"
          selectedId={ctrl.draft.graph.eval.answer_model}
        />
        <TuningProfileSelect
          {ctrl}
          label="Eval answer profile"
          path="graph.eval.answer_tuning_profile"
          bind:value={ctrl.draft.graph.eval.answer_tuning_profile}
        />
      </div>

      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.eval.judge_model"
          labelled
          embedded
          label="Eval judge model"
          selectedId={ctrl.draft.graph.eval.judge_model}
        />
        <TuningProfileSelect
          {ctrl}
          label="Eval judge profile"
          path="graph.eval.judge_tuning_profile"
          bind:value={ctrl.draft.graph.eval.judge_tuning_profile}
        />
      </div>
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
