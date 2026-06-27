<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
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
  <SectionCardMuted
    title="Embedding and Chunking"
    description={`Default embedding model: ${ctrl.draft.knowledge.default_embedding_model_resolved}. Chunking settings apply at document ingest.`}
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeEmbedding}
  >
    {#snippet headerActions()}
      {#if ctrl.draft?.knowledge.default_embedding_model_locked}
        <Badge variant="outline">Locked while indexed</Badge>
      {/if}
    {/snippet}
    <PrefModelPicker
      {ctrl}
      kind="embedding"
      path="knowledge.default_embedding_model"
      embedded
      label="Knowledge embedding model"
      selectedId={ctrl.draft.knowledge.default_embedding_model}
      busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
    />
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
  </SectionCardMuted>
{/if}
