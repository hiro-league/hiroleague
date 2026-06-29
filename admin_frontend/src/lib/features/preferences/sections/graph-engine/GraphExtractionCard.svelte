<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceIsAdvanced,
    preferenceTitle
  } from '$lib/features/preferences/shared/preferences-schema';
  import { usePrefAdvancedVisibility } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import PrefEmbedderDownload from '$lib/features/preferences/widgets/PrefEmbedderDownload.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  // "Reset to default" for the free-text extraction instructions (raw textarea, not a Pref* widget):
  // restores the built-in first-person extraction nudge carried as the field's schema default.
  const extractionDefault = $derived(
    preferenceFieldMeta(ctrl.fieldSchema, 'graph.custom_extraction_instructions')?.default
  );
  const extractionCanReset = $derived(
    typeof extractionDefault === 'string' &&
      ctrl.draft?.graph.custom_extraction_instructions !== extractionDefault
  );
  function resetExtractionInstructions() {
    if (!ctrl.draft || typeof extractionDefault !== 'string') return;
    ctrl.draft.graph.custom_extraction_instructions = extractionDefault;
    ctrl.markDirty();
  }

  // Ontology + instructions are raw controls (not Pref* widgets), so they don't gate on the "show
  // advanced" toggle on their own. Gate them here — WITHOUT registering a card auto-hide probe, since
  // the card's other content (model pickers) doesn't register and would otherwise collapse the card.
  const ontologyVis = usePrefAdvancedVisibility(() =>
    preferenceIsAdvanced(preferenceFieldMeta(ctrl.fieldSchema, 'graph.entity_ontology'))
  );
  const instructionsVis = usePrefAdvancedVisibility(() =>
    preferenceIsAdvanced(preferenceFieldMeta(ctrl.fieldSchema, 'graph.custom_extraction_instructions'))
  );
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Graph Extraction"
    description="Everything that builds the graph at ingest — the entity ontology, the heavy extraction model, the cheaper sub-step model, and the embedder. Changing any of these needs a re-ingest to rebuild the graph."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphExtraction}
  >
    <PrefFieldGrid>
      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.extraction_model"
          labelled
          embedded
          selectedId={ctrl.draft.graph.extraction_model}
        />
        <TuningProfileSelect
          {ctrl}
          path="graph.extraction_tuning_profile"
          bind:value={ctrl.draft.graph.extraction_tuning_profile}
        />
      </div>

      <div class="grid gap-3">
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="graph.small_model"
          labelled
          embedded
          selectedId={ctrl.draft.graph.small_model}
        />
        <TuningProfileSelect
          {ctrl}
          path="graph.small_tuning_profile"
          bind:value={ctrl.draft.graph.small_tuning_profile}
        />
      </div>

      <!-- Embedder + ontology share one grid column (moved to the end) so the column beside
           the tall instructions textarea stays filled instead of empty. -->
      <div class="grid gap-3">
        <div class="grid gap-2">
          <h4
            class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
          >
            Embedder model
            {#if ctrl.draft.graph.embedder_model_locked}
              <Badge variant="outline">Locked while indexed</Badge>
            {/if}
          </h4>
          <PrefModelPicker
            {ctrl}
            kind="embedding"
            path="graph.embedder_model"
            embedded
            selectedId={ctrl.draft.graph.embedder_model}
            emptyFallbackId={ctrl.draft.llm.default_embedder}
            busy={ctrl.busy || Boolean(ctrl.draft.graph.embedder_model_locked)}
          />
          <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.graph.embedder_model} />
        </div>
        {#if ontologyVis.visible}
          <FormField
            label={preferenceTitle(preferenceFieldMeta(ctrl.fieldSchema, 'graph.entity_ontology')) ??
              'Extraction ontology'}
            hint={preferenceHint(preferenceFieldMeta(ctrl.fieldSchema, 'graph.entity_ontology'))}
            hintTooltip
            anchor="graph.entity_ontology"
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
        {/if}
      </div>

      {#if instructionsVis.visible}
        <FormField
          label={preferenceTitle(
            preferenceFieldMeta(ctrl.fieldSchema, 'graph.custom_extraction_instructions')
          ) ?? 'Extraction instructions'}
          anchor="graph.custom_extraction_instructions"
          hint={preferenceHint(
            preferenceFieldMeta(ctrl.fieldSchema, 'graph.custom_extraction_instructions')
          )}
          hintTooltip
          showReset={extractionCanReset}
          onReset={resetExtractionInstructions}
        >
          <textarea
            class="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            rows="8"
            maxlength="2000"
            placeholder="e.g. Capture first-person preferences, goals, habits, and activities as facts even when only the speaker is named; treat the activity, topic, or object as the second entity."
            bind:value={ctrl.draft.graph.custom_extraction_instructions}
            oninput={ctrl.markDirty}
          ></textarea>
        </FormField>
      {/if}
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
