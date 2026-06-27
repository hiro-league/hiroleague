<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
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
  <SectionCardMuted
    title="Retrieval Agent Model"
    description="Model + profile for the agentic memory-retrieval loop (paired with the Retrieval Agent caps and prompt below)."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalModels}
  >
    <PrefFieldGrid>
      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.eval.retrieval_model"
          labelled
          embedded
          label="Retrieval agent model"
          selectedId={ctrl.draft.graph.eval.retrieval_model}
        />
        <TuningProfileSelect
          {ctrl}
          label="Retrieval agent profile"
          path="graph.eval.retrieval_tuning_profile"
          bind:value={ctrl.draft.graph.eval.retrieval_tuning_profile}
        />
      </div>
    </PrefFieldGrid>
  </SectionCardMuted>
{/if}
