<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefEmbedderDownload from '$lib/features/preferences/widgets/PrefEmbedderDownload.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Embedder & Chunking"
    description="The knowledge embedder (empty inherits the workspace default). Chunking applies at document ingest."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeEmbedding}
  >
    <!-- Knowledge embedder OVERRIDE. Locks once the collection is indexed (dimension-bound);
         empty inherits the General default. -->
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
        label="Knowledge embedder"
        selectedId={ctrl.draft.knowledge.default_embedding_model}
        emptyFallbackId={ctrl.draft.llm.default_embedder}
        busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
      />
      <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.knowledge.default_embedding_model} />
    </div>

    <PrefFieldGrid>
      <PrefNumberField
        {ctrl}
        path="knowledge.chunking.chunk_size"
        label="Chunk size"
        bind:value={ctrl.draft.knowledge.chunking.chunk_size}
      />
      <PrefNumberField
        {ctrl}
        path="knowledge.chunking.chunk_overlap"
        label="Chunk overlap"
        bind:value={ctrl.draft.knowledge.chunking.chunk_overlap}
      />
      <PrefToggleField
        {ctrl}
        path="knowledge.chunking.markdown.respect_headings"
        label="Respect markdown headings"
        bind:checked={ctrl.draft.knowledge.chunking.markdown.respect_headings}
      />
      <PrefToggleField
        {ctrl}
        path="knowledge.chunking.embed_structural_context"
        label="Embed structural context"
        bind:checked={ctrl.draft.knowledge.chunking.embed_structural_context}
      />
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
