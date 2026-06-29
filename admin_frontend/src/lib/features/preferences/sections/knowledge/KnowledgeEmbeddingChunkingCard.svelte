<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { GRAPH_BACKEND_LABELS } from '$lib/features/preferences/shared/preferences-enum-labels';
  import {
    preferenceFieldMeta,
    preferenceHint
  } from '$lib/features/preferences/shared/preferences-schema';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefEmbedderDownload from '$lib/features/preferences/widgets/PrefEmbedderDownload.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefSelectField from '$lib/features/preferences/widgets/PrefSelectField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  // Graph backend moved in from its own card. Folds the former "engine is shared" pointer into the
  // field's tooltip, appended to the field's schema description.
  const backendHint = $derived(
    [
      preferenceHint(preferenceFieldMeta(ctrl.fieldSchema, 'graph.backend')),
      'The graph engine itself — extraction/small models, embedder, search recipe, and reranker — is shared with Agent Memory and configured in the Graph Engine tab.'
    ]
      .filter(Boolean)
      .join(' ')
  );
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Indexing Options"
    description="Everything applied when documents are indexed — the knowledge embedder (empty inherits the workspace default), document chunking, and the knowledge graph backend."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeEmbedding}
  >
    <!-- Knowledge embedder OVERRIDE. Locks once the collection is indexed (dimension-bound);
         empty inherits the General default. Half-width (lone) like every other field. -->
    <PrefFieldGrid>
      <div class="grid gap-2">
        <h4
          class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
        >
          Knowledge embedder
          {#if ctrl.draft.knowledge.default_embedding_model_locked}
            <Badge variant="outline">Locked while indexed</Badge>
          {/if}
        </h4>
        <PrefModelPicker
          {ctrl}
          kind="embedding"
          path="knowledge.default_embedding_model"
          embedded
          selectedId={ctrl.draft.knowledge.default_embedding_model}
          emptyFallbackId={ctrl.draft.llm.default_embedder}
          busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
        />
        <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.knowledge.default_embedding_model} />
      </div>
    </PrefFieldGrid>

    <PrefFieldGrid>
      <PrefNumberField
        {ctrl}
        path="knowledge.chunking.chunk_size"
        bind:value={ctrl.draft.knowledge.chunking.chunk_size}
      />
      <PrefNumberField
        {ctrl}
        path="knowledge.chunking.chunk_overlap"
        bind:value={ctrl.draft.knowledge.chunking.chunk_overlap}
      />
      <PrefToggleField
        {ctrl}
        path="knowledge.chunking.markdown.respect_headings"
        bind:checked={ctrl.draft.knowledge.chunking.markdown.respect_headings}
      />
      <PrefToggleField
        {ctrl}
        path="knowledge.chunking.embed_structural_context"
        bind:checked={ctrl.draft.knowledge.chunking.embed_structural_context}
      />
      <PrefSelectField
        {ctrl}
        path="graph.backend"
        hint={backendHint}
        options={GRAPH_BACKEND_LABELS}
        bind:value={ctrl.draft.graph.backend}
      />
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
