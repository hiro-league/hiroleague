<script lang="ts">
  import { Search } from '@lucide/svelte';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import type { KnowledgeBrowseModel } from '$lib/features/knowledge/state/knowledge-browse.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import {
    documentFileTypeLabel,
    documentFileTypeTooltip,
    documentStatusErrorTooltip,
    formatBytes
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import { KNOWLEDGE_TABLE_HEAD } from '$lib/features/knowledge/shared/knowledge-ui';

  type Props = {
    browse: KnowledgeBrowseModel;
    options: KnowledgeOptionsModel;
    onPreview: (doc: KnowledgeDocument) => void;
    onOpenChunks: (doc: KnowledgeDocument) => void;
  };

  let { browse, options, onPreview, onOpenChunks }: Props = $props();

  let selectAllCheckboxEl = $state<HTMLInputElement | null>(null);

  const documentSort = $derived(browse.documentSort);
  const selectAllCheckboxTooltip = $derived(
    browse.sortedDocuments.length === 0
      ? 'No documents'
      : browse.allDocumentsSelected
        ? 'Deselect all documents'
        : 'Select all documents'
  );

  $effect(() => {
    if (selectAllCheckboxEl) {
      selectAllCheckboxEl.indeterminate = browse.someDocumentsSelected;
    }
  });
</script>

<AdminTableShell stickyHead maxBodyHeight="280px">
  <thead class={KNOWLEDGE_TABLE_HEAD}>
    <tr>
      <th class="w-10 px-3 py-2">
        <input
          bind:this={selectAllCheckboxEl}
          type="checkbox"
          aria-label={selectAllCheckboxTooltip}
          title={selectAllCheckboxTooltip}
          disabled={browse.sortedDocuments.length === 0}
          checked={browse.allDocumentsSelected}
          onchange={browse.toggleSelectAllDocuments}
        />
      </th>
      <AdminTableHeaderCell column="title" sort={documentSort}>Title</AdminTableHeaderCell>
      <AdminTableHeaderCell column="owner" sort={documentSort}>Owner</AdminTableHeaderCell>
      <AdminTableHeaderCell column="category" sort={documentSort}>Category</AdminTableHeaderCell>
      <AdminTableHeaderCell column="tags" sort={documentSort}>Tags</AdminTableHeaderCell>
      <AdminTableHeaderCell column="chunks" sort={documentSort}>Chunks</AdminTableHeaderCell>
      <AdminTableHeaderCell column="ingested_at" sort={documentSort}>Ingested</AdminTableHeaderCell>
      <AdminTableHeaderCell column="type" sort={documentSort}>Type</AdminTableHeaderCell>
      <AdminTableHeaderCell column="size" sort={documentSort}>Size</AdminTableHeaderCell>
      <AdminTableHeaderCell column="path" sort={documentSort}>Path</AdminTableHeaderCell>
      <AdminTableHeaderCell column="status" sort={documentSort}>Status</AdminTableHeaderCell>
    </tr>
  </thead>
  <tbody>
    {#each browse.sortedDocuments as doc (doc.id)}
      <tr class="border-t">
        <td class="px-3 py-2">
          <input
            type="checkbox"
            aria-label={`Select ${doc.title}`}
            checked={!!browse.selectedDocuments[doc.id]}
            onchange={(event) => {
              browse.toggleDocumentSelection(doc.id, event.currentTarget.checked);
            }}
          />
        </td>
        <td class="max-w-[280px] truncate px-3 py-2 font-medium">
          <span class="inline-flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              class="shrink-0 rounded-sm p-0.5 text-primary/85 hover:bg-primary/10 hover:text-primary"
              aria-label={`Preview ${doc.title}`}
              onclick={() => onPreview(doc)}
            >
              <Search size={14} aria-hidden="true" />
            </button>
            <span class="truncate">{doc.title}</span>
          </span>
        </td>
        <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">{doc.owner_kind}/{doc.owner_id}</td>
        <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">
          {options.categoryLabel(doc.category_id)}{doc.subcategory_id
            ? ` > ${options.categoryLabel(doc.subcategory_id)}`
            : ''}
        </td>
        <td class="max-w-[180px] px-3 py-2">
          {#if (doc.tags ?? []).length > 0}
            <span class="flex flex-wrap gap-1">
              {#each doc.tags ?? [] as tag (tag)}
                <Badge variant="secondary" class="text-xs font-normal">{tag}</Badge>
              {/each}
            </span>
          {:else}
            <span class="text-muted-foreground">—</span>
          {/if}
        </td>
        <td class="px-3 py-2">
          <button
            type="button"
            class="rounded-sm px-1 py-0.5 font-sans text-sm tabular-nums text-primary hover:bg-primary/10 hover:underline"
            aria-label={`View chunks for ${doc.title}`}
            title={`View chunks for ${doc.title}`}
            onclick={() => void onOpenChunks(doc)}
          >
            {doc.chunk_count ?? '—'}
          </button>
        </td>
        <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">
          {formatChatTimestamp(doc.ingested_at)}
        </td>
        <td class="px-3 py-2" title={documentFileTypeTooltip(doc)}>
          <Badge variant="outline">{documentFileTypeLabel(doc)}</Badge>
        </td>
        <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">
          {formatBytes(doc.size_bytes)}
        </td>
        <td class="max-w-[220px] truncate px-3 py-2 text-muted-foreground" title={doc.source_uri}>
          {doc.source_uri}
        </td>
        <td class="px-3 py-2" title={documentStatusErrorTooltip(doc)}>
          <Badge variant={doc.status === 'ready' ? 'success' : doc.status === 'failed' ? 'destructive' : 'outline'}>
            {doc.status}
          </Badge>
        </td>
      </tr>
    {/each}
  </tbody>
</AdminTableShell>
