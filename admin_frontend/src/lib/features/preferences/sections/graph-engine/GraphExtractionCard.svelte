<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { GRAPH_EXTRACTION_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Graph Extraction"
    description="Everything that builds the graph at ingest — the entity ontology, the heavy extraction model, the cheaper sub-step model, and the embedder. Changing any of these needs a re-ingest to rebuild the graph."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphExtraction}
  >
    <FormField
      label="Extraction ontology"
      hint={GRAPH_EXTRACTION_COPY.entityOntology}
      class="max-w-md"
    >
      <select
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.graph.entity_ontology}
        onchange={ctrl.markDirty}
      >
        <option value="open">Open (no predefined types)</option>
        <option value="typed">Typed (Person / Place / Organization / Event / Object)</option>
      </select>
    </FormField>

    <FormField
      label="Extraction instructions"
      hint={GRAPH_EXTRACTION_COPY.customInstructions}
    >
      <textarea
        class="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        rows="4"
        maxlength="2000"
        placeholder="e.g. Capture first-person preferences, goals, habits, and activities as facts even when only the speaker is named; treat the activity, topic, or object as the second entity."
        bind:value={ctrl.draft.graph.custom_extraction_instructions}
        oninput={ctrl.markDirty}
      ></textarea>
    </FormField>

    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="graph.extraction_model"
      labelled
      embedded
      label="Extraction model"
      hint={GRAPH_EXTRACTION_COPY.extractionModel}
      selectedId={ctrl.draft.graph.extraction_model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Extraction profile"
      hint={GRAPH_EXTRACTION_COPY.extractionProfile}
      class="max-w-md"
      bind:value={ctrl.draft.graph.extraction_tuning_profile}
    />

    <PrefModelPicker
      {ctrl}
      kind="chat"
      path="graph.small_model"
      labelled
      embedded
      label="Smaller extraction model"
      hint={GRAPH_EXTRACTION_COPY.smallModel}
      selectedId={ctrl.draft.graph.small_model}
    />
    <TuningProfileSelect
      {ctrl}
      label="Smaller extraction profile"
      hint={GRAPH_EXTRACTION_COPY.smallProfile}
      class="max-w-md"
      bind:value={ctrl.draft.graph.small_tuning_profile}
    />

    <PrefModelPicker
      {ctrl}
      kind="embedding"
      path="graph.embedder_model"
      labelled
      embedded
      label="Embedder model"
      hint={GRAPH_EXTRACTION_COPY.embedderModel}
      selectedId={ctrl.draft.graph.embedder_model}
    />
  </SectionCardMuted>
{/if}
