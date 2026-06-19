<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { KNOWLEDGE_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

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
      hint={KNOWLEDGE_COPY.embedderModel}
      selectedId={ctrl.draft.knowledge.default_embedding_model}
      busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
    />
    <div class="grid gap-3 md:grid-cols-2">
      <FormField label="Chunk size">
        <input
          type="number"
          min="200"
          max="8000"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.chunking.chunk_size}
          oninput={ctrl.markDirty}
        />
      </FormField>
      <FormField label="Chunk overlap">
        <input
          type="number"
          min="0"
          max="2000"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.chunking.chunk_overlap}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </div>
    <SettingToggle
      label="Respect markdown headings"
      bind:checked={ctrl.draft.knowledge.chunking.markdown.respect_headings}
      onchange={ctrl.markDirty}
    />
    <SettingToggle
      label="Embed structural context"
      bind:checked={ctrl.draft.knowledge.chunking.embed_structural_context}
      onchange={ctrl.markDirty}
    >
      {#snippet details()}
        Prefix each chunk's embedded text with its document title and heading path so every chunk
        — including continuation pieces — carries its section context. Applies to new ingests;
        changing this requires re-ingesting existing documents.
      {/snippet}
    </SettingToggle>
  </SectionCardMuted>
{/if}
