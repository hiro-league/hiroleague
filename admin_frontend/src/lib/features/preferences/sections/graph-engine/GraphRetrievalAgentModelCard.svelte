<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import ActivePromptLibraryField from '$lib/features/preferences/widgets/prompts/ActivePromptLibraryField.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Retrieval Agent Model & Prompt"
    description="Model, profile, and system prompt for the agentic memory-retrieval loop (the Retrieval Agent caps below feed its placeholders)."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalModels}
  >
    <!-- Left column: model + profile. Right column: single active-prompt control (select the active
         profile + New/Edit/Duplicate icons that open the editor dialog). Two filled columns. -->
    <PrefFieldGrid>
      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.eval.retrieval_model"
          labelled
          embedded
          selectedId={ctrl.draft.graph.eval.retrieval_model}
        />
        <TuningProfileSelect
          {ctrl}
          path="graph.eval.retrieval_tuning_profile"
          bind:value={ctrl.draft.graph.eval.retrieval_tuning_profile}
        />
      </div>

      <div class="grid gap-3">
        <ActivePromptLibraryField
          {ctrl}
          dictPath="graph.eval.retrieval_agent_prompts"
          activeIdPath="graph.eval.active_retrieval_agent_prompt_id"
          hint={"Drives the memory eval's recall leg. Placeholders {MAX_AGENT_TURNS}, {MAX_PARALLEL_SEARCHES}, and {MAX_LIMIT} are filled from the Retrieval Agent caps card at runtime."}
          ariaLabel="Mem-eval retrieval agent prompt (markdown)"
          editorLabel="Retrieval agent prompt editor"
        />
      </div>
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
