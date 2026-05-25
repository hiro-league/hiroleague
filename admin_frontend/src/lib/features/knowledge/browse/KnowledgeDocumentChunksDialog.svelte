<script lang="ts">
  import { BookText, Code, Database, Search } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import KnowledgeChunkMarkdownPreview from '$lib/features/knowledge/shared/KnowledgeChunkMarkdownPreview.svelte';
  import type { KnowledgeBrowseModel } from '$lib/features/knowledge/state/knowledge-browse.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import {
    chunkTextByteSize,
    documentCategoryDisplay,
    documentMimeLabel,
    documentMetadataTitleAttr,
    fileName,
    formatBytes,
    readKnowledgeChunkMarkdownFormat,
    writeKnowledgeChunkMarkdownFormat
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import { KNOWLEDGE_SECTION_TITLE } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  type Props = {
    open: boolean;
    browse: KnowledgeBrowseModel;
    options: KnowledgeOptionsModel;
    onAskForDocument: (document: KnowledgeDocument) => void;
  };

  let { open = $bindable(false), browse, options, onAskForDocument }: Props = $props();

  let chunkMarkdownFormat = $state(readKnowledgeChunkMarkdownFormat());

  const doc = $derived(browse.activeDocument);
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="flex h-[min(85vh,920px)] w-[min(92vw,960px)] max-w-[min(92vw,960px)] flex-col gap-0 overflow-hidden bg-background p-0 sm:max-w-[min(92vw,960px)]"
    showCloseButton={true}
  >
    <Dialog.Header class="shrink-0 border-b border-border/80 bg-muted/45 px-4 py-3.5 pr-12">
      <div class="flex min-w-0 items-start gap-3">
        <Database size={17} class="mt-0.5 shrink-0 text-muted-foreground" />
        <div class="min-w-0 flex-1">
          <Dialog.Title class="font-sans text-lg font-semibold leading-tight">
            <span class={cn(KNOWLEDGE_SECTION_TITLE, 'font-sans text-lg')}>Document Chunks</span>
          </Dialog.Title>
          {#if doc}
            <Dialog.Description class="mt-2 space-y-2">
              <span
                class="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 text-sm font-normal text-muted-foreground"
                title={doc.source_uri}
              >
                <span class="font-medium text-foreground">{doc.title}</span>
                <span class="select-none text-border" aria-hidden="true">·</span>
                <span class="max-w-full truncate font-mono text-xs">{fileName(doc.source_uri)}</span>
                <span class="select-none text-border" aria-hidden="true">·</span>
                <span class="max-w-full truncate font-mono text-xs">{doc.source_uri}</span>
              </span>
              <span
                class="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted-foreground"
                title={documentMetadataTitleAttr(doc, browse.detailTags, options.categoryLabel)}
              >
                <span class="whitespace-nowrap">
                  <span class="font-semibold text-foreground">Owner:</span>
                  {doc.owner_kind}/{doc.owner_id}
                </span>
                <span class="whitespace-nowrap">
                  <span class="font-semibold text-foreground">Category:</span>
                  {documentCategoryDisplay(doc, options.categoryLabel)}
                </span>
                <span class="min-w-0">
                  <span class="font-semibold text-foreground">Tags:</span>
                  {browse.detailTags.length > 0 ? browse.detailTags.join(', ') : '—'}
                </span>
                <span class="whitespace-nowrap font-mono">{documentMimeLabel(doc)}</span>
                <span class="whitespace-nowrap tabular-nums">{formatBytes(doc.size_bytes)}</span>
                <span class="whitespace-nowrap tabular-nums">{formatChatTimestamp(doc.ingested_at)}</span>
              </span>
            </Dialog.Description>
          {/if}
        </div>
        <div class="flex shrink-0 items-center gap-1">
          {#if doc}
            <Button
              variant="ghost"
              size="icon"
              class="size-8 text-muted-foreground hover:text-foreground"
              type="button"
              aria-label="Test query against this document"
              title="Test query against this document"
              onclick={() => onAskForDocument(doc)}
            >
              <Search size={16} aria-hidden="true" />
            </Button>
          {/if}
          <Button
            variant="ghost"
            size="icon"
            class="size-8 text-muted-foreground hover:text-foreground"
            type="button"
            aria-label={chunkMarkdownFormat ? 'Show raw chunk text' : 'Show formatted markdown'}
            aria-pressed={chunkMarkdownFormat}
            title={chunkMarkdownFormat ? 'Formatted markdown — click for raw text' : 'Raw text — click for formatted markdown'}
            onclick={() => {
              chunkMarkdownFormat = !chunkMarkdownFormat;
              writeKnowledgeChunkMarkdownFormat(chunkMarkdownFormat);
            }}
          >
            {#if chunkMarkdownFormat}
              <BookText size={16} aria-hidden="true" />
            {:else}
              <Code size={16} aria-hidden="true" />
            {/if}
          </Button>
          <Badge variant="outline">
            {browse.chunks.length}{#if doc?.chunk_count != null && doc.chunk_count !== browse.chunks.length}
              / {doc.chunk_count}{/if}
          </Badge>
        </div>
      </div>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-auto bg-card p-4">
      <div class="rounded-md border">
        {#if !doc}
          <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No document selected</div>
        {:else if browse.chunks.length === 0}
          <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No chunks</div>
        {:else}
          {#each browse.chunks as chunk (chunk.point_id)}
            <article class="grid gap-2 border-t px-3 py-3 first:border-t-0">
              <div class="flex min-w-0 items-center gap-2">
                <Badge class="shrink-0 rounded-md font-mono tabular-nums" variant="secondary">#{chunk.ord}</Badge>
                {#if chunk.heading_path}
                  <span class="min-w-0 truncate font-sans text-xs text-muted-foreground">{chunk.heading_path}</span>
                {/if}
                <Badge class="shrink-0 font-mono tabular-nums" variant="outline">
                  {formatBytes(chunkTextByteSize(chunk.text))}
                </Badge>
              </div>
              {#if chunkMarkdownFormat}
                <KnowledgeChunkMarkdownPreview markdown={chunk.text} class="text-muted-foreground" />
              {:else}
                <p class="whitespace-pre-wrap font-sans text-sm leading-6 text-muted-foreground">{chunk.text}</p>
              {/if}
            </article>
          {/each}
          {#if browse.chunkHasMore}
            <div class="border-t px-3 py-3 text-center">
              <Button
                variant="outline"
                size="sm"
                disabled={browse.loadingMoreChunks}
                onclick={() => void browse.loadMoreChunks()}
              >
                {browse.loadingMoreChunks ? 'Loading…' : 'Load more chunks'}
              </Button>
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>
