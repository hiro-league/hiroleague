<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { GRAPH_EVAL_MODELS_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Evaluation Models"
    description="Models + profiles the eval harness uses — the answer step (memory track) and the judge (both tracks). Eval-only; the knowledge track answers with the production pipeline, not the answer model here."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalModels}
  >
    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="graph.eval.answer_model"
      labelled
      embedded
      label="Eval answer model"
      hint={GRAPH_EVAL_MODELS_COPY.answerModel}
      selectedId={ctrl.draft.graph.eval.answer_model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Eval answer profile"
      hint={GRAPH_EVAL_MODELS_COPY.answerProfile}
      class="max-w-md"
      bind:value={ctrl.draft.graph.eval.answer_tuning_profile}
    />

    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="graph.eval.judge_model"
      labelled
      embedded
      label="Eval judge model"
      hint={GRAPH_EVAL_MODELS_COPY.judgeModel}
      selectedId={ctrl.draft.graph.eval.judge_model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Eval judge profile"
      hint={GRAPH_EVAL_MODELS_COPY.judgeProfile}
      class="max-w-md"
      bind:value={ctrl.draft.graph.eval.judge_tuning_profile}
    />

    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="graph.eval.retrieval_model"
      labelled
      embedded
      label="Retrieval agent model"
      hint={GRAPH_EVAL_MODELS_COPY.retrievalModel}
      selectedId={ctrl.draft.graph.eval.retrieval_model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Retrieval agent profile"
      hint={GRAPH_EVAL_MODELS_COPY.retrievalProfile}
      class="max-w-md"
      bind:value={ctrl.draft.graph.eval.retrieval_tuning_profile}
    />
  </SectionCardMuted>
{/if}
