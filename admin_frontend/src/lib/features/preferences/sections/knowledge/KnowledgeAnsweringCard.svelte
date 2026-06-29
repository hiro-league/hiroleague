<script lang="ts">
  import PromptField from '$lib/features/preferences/widgets/prompts/PromptField.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { KNOWLEDGE_LANGUAGE_POLICY_LABELS } from '$lib/features/preferences/shared/preferences-enum-labels';
  import { knowledgeAnsweringModelHint } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefSelectField from '$lib/features/preferences/widgets/PrefSelectField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Knowledge Answering (Ask Tab)"
    description={knowledgeAnsweringModelHint(ctrl.draft)}
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeAnsweringModel}
  >
    <!-- Query rewrite (merged in from its own card) — first row. -->
    <PrefFieldGrid>
      <PrefToggleField
        {ctrl}
        path="knowledge.rewrite.default_on"
        hint="Optional LLM step that rewrites a question before retrieval — normalizes wording and extracts literal keywords. Reuses the answering model; toggled per query on the Ask tab."
        bind:checked={ctrl.draft.knowledge.rewrite.default_on}
      />
      <PromptField
        {ctrl}
        path="knowledge.rewrite.prompt"
        hint="Sent as the system prompt for the rewrite call. Keep the instruction to copy proper nouns and identifiers verbatim so the BM25 keyword branch keeps its exact-match signal."
        ariaLabel="Knowledge query rewrite prompt (markdown)"
        editorLabel="Rewrite prompt editor"
      />
    </PrefFieldGrid>

    <!-- Left column: the answering model selection. Right column: answering output behavior. -->
    <PrefFieldGrid>
      <div class="grid gap-3">
        <h4 class="font-sans text-base font-semibold leading-snug text-foreground">
          Knowledge Answering Model
        </h4>
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="knowledge.answering.model"
          embedded
          selectedId={ctrl.draft.knowledge.answering.model}
        />
        <TuningProfileSelect
          {ctrl}
          path="knowledge.default_tuning_profile"
          value={ctrl.draft.knowledge.default_tuning_profile}
          scope="knowledge"
        />
      </div>
      <div class="grid gap-3">
        <PromptField
          {ctrl}
          path="knowledge.answering.prompt"
          hint={'Base system prompt for answer generation. The relaxed default allows partial answers and avoids a bare "I don\'t know" when the context covers part of the question; use "Restore default" in the editor to bring it back. The citation and language settings below are appended automatically.'}
          ariaLabel="Knowledge answering prompt (markdown)"
          editorLabel="Answering prompt editor"
        />
        <PrefSelectField
          {ctrl}
          path="knowledge.answering.language_policy"
          options={KNOWLEDGE_LANGUAGE_POLICY_LABELS}
          bind:value={ctrl.draft.knowledge.answering.language_policy}
        />
        <PrefToggleField
          {ctrl}
          path="knowledge.answering.cite_sources"
          bind:checked={ctrl.draft.knowledge.answering.cite_sources}
        />
      </div>
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
