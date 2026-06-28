<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint
  } from '$lib/features/preferences/shared/preferences-schema';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PromptLibraryField from '$lib/features/preferences/widgets/prompts/PromptLibraryField.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const activePromptEntries = $derived(
    Object.entries(ctrl.draft?.graph.eval.retrieval_agent_prompts ?? {}).sort(([ka, a], [kb, b]) =>
      ka === 'default' ? -1 : kb === 'default' ? 1 : a.label.localeCompare(b.label)
    )
  );
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Retrieval Agent Model & Prompt"
    description="Model, profile, and system prompt for the agentic memory-retrieval loop (the Retrieval Agent caps below feed its placeholders)."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalModels}
  >
    <!-- Left column: model + profile. Right column: prompt profile select + prompt library.
         Two filled columns of similar height — no full-width spread, no empty cell. -->
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

      <div class="grid gap-3">
        <FormField
          label="Active prompt profile"
          hint={preferenceHint(
            preferenceFieldMeta(ctrl.fieldSchema, 'graph.eval.active_retrieval_agent_prompt_id')
          )}
          hintTooltip
        >
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.eval.active_retrieval_agent_prompt_id}
            onchange={ctrl.markDirty}
          >
            {#each activePromptEntries as [id, profile] (id)}
              <option value={id}>{profile.label}{profile.locked ? ' 🔒' : ''}</option>
            {/each}
          </select>
        </FormField>

        <PromptLibraryField
          {ctrl}
          dictPath="graph.eval.retrieval_agent_prompts"
          label="Retrieval Agent Prompt"
          hint={"Drives the memory eval's recall leg. Placeholders {MAX_AGENT_TURNS}, {MAX_PARALLEL_SEARCHES}, and {MAX_LIMIT} are filled from the Retrieval Agent caps card at runtime."}
          ariaLabel="Mem-eval retrieval agent prompt (markdown)"
          editorLabel="Retrieval agent prompt editor"
          activeIdPath="graph.eval.active_retrieval_agent_prompt_id"
        />
      </div>
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
