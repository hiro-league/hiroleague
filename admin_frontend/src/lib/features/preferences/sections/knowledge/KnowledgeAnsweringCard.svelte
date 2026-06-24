<script lang="ts">
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { KNOWLEDGE_LANGUAGE_POLICY_LABELS } from '$lib/features/preferences/shared/preferences-enum-labels';
  import { knowledgeAnsweringModelHint } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
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
  <SectionCardMuted
    title="Knowledge answering (Ask Tab only)"
    description={knowledgeAnsweringModelHint(ctrl.draft)}
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeAnsweringModel}
  >
    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="knowledge.answering.model"
      embedded
      label="Knowledge answering model"
      selectedId={ctrl.draft.knowledge.answering.model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Knowledge answering model profile"
      class="max-w-md"
      value={ctrl.draft.knowledge.default_tuning_profile}
      scope="knowledge"
    />
    <MarkdownEditorPreview
      editorLabel="Answering prompt editor"
      previewLabel="Preview"
      ariaLabel="Knowledge answering prompt (markdown)"
      bind:value={ctrl.draft.knowledge.answering.prompt}
      defaultValue={ctrl.promptDefaults['knowledge.answering.prompt']}
      onInput={ctrl.markDirty}
    />
    <p class="text-xs text-muted-foreground">
      Base system prompt for answer generation. Leave blank to use the relaxed default, which
      allows partial answers and avoids a bare "I don't know" when the context covers part of the
      question. The citation and language settings below are appended automatically.
    </p>
    <PrefToggleField
      {ctrl}
      path="knowledge.answering.cite_sources"
      label="Cite sources"
      bind:checked={ctrl.draft.knowledge.answering.cite_sources}
    />
    <PrefSelectField
      {ctrl}
      path="knowledge.answering.language_policy"
      label="Language policy"
      options={KNOWLEDGE_LANGUAGE_POLICY_LABELS}
      class="max-w-md"
      bind:value={ctrl.draft.knowledge.answering.language_policy}
    />
  </SectionCardMuted>
{/if}
