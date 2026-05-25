<script lang="ts">
  import { Edit, FilterX, RefreshCw, Repeat2, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import KnowledgeBrowseDocumentsTable from '$lib/features/knowledge/browse/KnowledgeBrowseDocumentsTable.svelte';
  import type { KnowledgeBrowseModel } from '$lib/features/knowledge/state/knowledge-browse.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { KNOWLEDGE_SECTION_CARD, KNOWLEDGE_SECTION_TITLE } from '$lib/features/knowledge/shared/knowledge-ui';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    browse: KnowledgeBrowseModel;
    options: KnowledgeOptionsModel;
    hasSelection: boolean;
    selectionLabel: string;
    onUpdateMetadata: () => void;
    onReingest: () => void;
    onDelete: () => void;
    onPreview: (doc: KnowledgeDocument) => void;
    onOpenChunks: (doc: KnowledgeDocument) => void;
  };

  let {
    browse,
    options,
    hasSelection,
    selectionLabel,
    onUpdateMetadata,
    onReingest,
    onDelete,
    onPreview,
    onOpenChunks
  }: Props = $props();
</script>

<div class={KNOWLEDGE_SECTION_CARD}>
  <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={KNOWLEDGE_SECTION_TITLE}>Document List</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {browse.documentTotal} documents
        {#if hasSelection}
          <span class="mx-1.5 select-none text-border" aria-hidden="true">·</span>
          {selectionLabel}
        {/if}
      </span>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" disabled={!hasSelection} onclick={onUpdateMetadata}>
        <Edit size={16} />
        Update metadata
      </Button>
      <Button variant="outline" disabled={!hasSelection} onclick={onReingest}>
        <Repeat2 size={16} />
        Re-ingest
      </Button>
      <Button variant="outline" disabled={!hasSelection} onclick={onDelete}>
        <Trash2 size={16} />
        Delete
      </Button>
      <Button variant="outline" onclick={() => void browse.loadDocuments()} disabled={browse.loadingDocs}>
        <RefreshCw size={16} class={cn(browse.loadingDocs && 'animate-spin')} />
        Refresh
      </Button>
    </div>
  </div>

  {#if browse.loadingDocs && browse.documents.length === 0}
    <InlineLoading label="Loading documents…" />
  {:else if browse.documents.length === 0}
    <div
      class="flex flex-wrap items-center justify-center gap-2 rounded-md border border-dashed border-border bg-background/40 px-4 py-6 text-center"
    >
      <p class="font-sans text-sm text-muted-foreground">No documents</p>
      {#if browse.hasBrowseFilters}
        <Button variant="outline" class="h-8" onclick={() => browse.clearBrowseFilters()}>
          <FilterX size={15} />
          Clear
        </Button>
      {/if}
    </div>
  {:else}
    <KnowledgeBrowseDocumentsTable {browse} {options} {onPreview} {onOpenChunks} />
  {/if}
</div>
