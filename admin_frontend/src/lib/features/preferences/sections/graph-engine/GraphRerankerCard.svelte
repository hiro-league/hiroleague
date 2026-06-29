<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefTextField from '$lib/features/preferences/widgets/PrefTextField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Graphiti Reranker (Cross-encoder)"
    description="Reranks graph fact-search candidates with a real cross-encoder. Only active when the Search recipe above is set to Cross-encoder — otherwise these settings are disabled. Reuses the same reranker models as the flat path (cloud or local)."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngineReranker}
  >
    {#if ctrl.draft.graph.search_recipe !== 'cross_encoder'}
      <p class="rounded-md border border-border/50 bg-card/45 px-3 py-2 font-sans text-xs text-muted-foreground">
        Set <span class="font-medium">Search recipe → Cross-encoder</span> above to enable these
        settings.
      </p>
    {/if}
    <fieldset
      disabled={ctrl.draft.graph.search_recipe !== 'cross_encoder'}
      class="grid gap-4 border-0 p-0 disabled:opacity-50"
    >
      <PrefModelPicker
        {ctrl}
        kind="rerank"
        path="graph.reranker.model_id"
        embedded
        selectedId={ctrl.draft.graph.reranker.model_id}
        emptyFallbackId={ctrl.draft.llm.default_reranker}
      />
      <PrefFieldGrid>
        <PrefNumberField
          {ctrl}
          path="graph.reranker.min_relevance"
          bind:value={ctrl.draft.graph.reranker.min_relevance}
        />
        <PrefTextField
          {ctrl}
          path="graph.reranker.device"
          placeholder="auto"
          bind:value={ctrl.draft.graph.reranker.device}
        />
      </PrefFieldGrid>
    </fieldset>
  </PrefSectionCard>
{/if}
