<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { GRAPH_RERANKER_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
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
        label="Reranker model"
        hint={GRAPH_RERANKER_COPY.model}
        selectedId={ctrl.draft.graph.reranker.model_id}
      />
      <div class="grid gap-3 md:grid-cols-2">
        <FormField
          label="Min relevance"
          hint={GRAPH_RERANKER_COPY.minRelevance}
        >
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.reranker.min_relevance}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField
          label="Device (local only)"
          hint={GRAPH_RERANKER_COPY.device}
        >
          <input
            type="text"
            placeholder="auto"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.reranker.device}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
    </fieldset>
  </SectionCardMuted>
{/if}
