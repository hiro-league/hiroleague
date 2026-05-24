<script lang="ts">
  import { BookText, ChevronDown, ChevronUp, Code, Database, FileText, FilterX, RefreshCw, Search, Trash2 } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSearch from '$lib/components/page/table/AdminFilterBarSearch.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminMasterDetail from '$lib/components/page/table/AdminMasterDetail.svelte';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { KnowledgeDocument, KnowledgeScannedFile } from '$lib/api/knowledge';
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import KnowledgeChunkMarkdownPreview from '$lib/features/knowledge/shared/KnowledgeChunkMarkdownPreview.svelte';
  import KnowledgeFilePreviewDialog from '$lib/features/knowledge/shared/file-preview/KnowledgeFilePreviewDialog.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import {
    chunkTextByteSize,
    documentCategoryDisplay,
    documentFileTypeLabel,
    documentFileTypeTooltip,
    documentMimeLabel,
    documentMetadataTitleAttr,
    documentStatusErrorTooltip,
    documentToPreviewFile,
    fileName,
    formatBytes,
    optionalInt,
    readKnowledgeChunkMarkdownFormat,
    writeKnowledgeChunkMarkdownFormat
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SECTION_TITLE,
    KNOWLEDGE_SELECT,
    KNOWLEDGE_TABLE_HEAD,
    cnKnowledgeBrowseDocRow
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';
  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const browse = $derived(ctl.browse);
  const ingest = $derived(ctl.ingest);
  const options = $derived(ctl.options);

  let docsExpanded = $state(true);
  let chunkMarkdownFormat = $state(readKnowledgeChunkMarkdownFormat());
  let previewOpen = $state(false);
  let previewFile = $state<KnowledgeScannedFile | null>(null);
  let deleteOpen = $state(false);
  let deleteTarget = $state<KnowledgeDocument | null>(null);
  let deleting = $state(false);
  const toasts = createToastNotifier();
  const notify = toasts.notify;

  $effect(() => {
    if (!deleteOpen) {
      deleteTarget = null;
    }
  });

  async function handleUpdateMetadata() {
    const saved = await browse.saveActiveMetadata();
    if (saved) {
      notify('success', 'Document metadata updated.');
    }
  }

  async function confirmDeleteDocument() {
    if (!deleteTarget) return;
    const title = deleteTarget.title;
    deleting = true;
    const deleted = await browse.deleteDocument(deleteTarget.id);
    deleting = false;
    if (deleted) {
      deleteOpen = false;
      notify('success', `"${title}" removed from the knowledge index.`);
    }
  }

  function openDeleteDialog(doc: KnowledgeDocument) {
    deleteTarget = doc;
    deleteOpen = true;
  }

  function openDocumentPreview(doc: (typeof browse.sortedDocuments)[number]) {
    previewFile = documentToPreviewFile(doc);
    previewOpen = true;
  }

  const documentSort = $derived(browse.documentSort);
</script>

<section class="grid gap-4">
  <div class={KNOWLEDGE_SECTION_CARD}>
    <div class="mb-3 flex items-center gap-2">
      <Button
        variant="ghost"
        size="icon"
        class="shrink-0 text-muted-foreground hover:text-foreground"
        type="button"
        aria-expanded={docsExpanded}
        aria-controls="knowledge-browse-docs-panel"
        aria-label={docsExpanded ? 'Collapse document list' : 'Expand document list'}
        title={docsExpanded ? 'Collapse document list' : 'Expand document list'}
        onclick={() => {
          docsExpanded = !docsExpanded;
        }}
      >
        {#if docsExpanded}
          <ChevronUp size={18} strokeWidth={2} aria-hidden="true" />
        {:else}
          <ChevronDown size={18} strokeWidth={2} aria-hidden="true" />
        {/if}
      </Button>
      <FileText size={17} class="text-primary" />
      <h3 class={KNOWLEDGE_SECTION_TITLE}>Document List</h3>
      <Badge variant="outline">{browse.documentTotal}</Badge>
      <Button class="ml-auto" variant="outline" onclick={() => void browse.loadDocuments()} disabled={browse.loadingDocs}>
        <RefreshCw size={16} class={cn(browse.loadingDocs && 'animate-spin')} />
        Refresh
      </Button>
    </div>

    {#if docsExpanded}
      <div id="knowledge-browse-docs-panel" class="grid gap-3">
        <div class={KNOWLEDGE_METADATA_SHELL}>
          <div class="flex items-center gap-2">
            <div class="font-sans text-sm font-medium">Document filters</div>
            <Button
              variant="ghost"
              size="icon"
              class={cn(
                'size-7 shrink-0',
                browse.hasBrowseFilters
                  ? 'text-destructive hover:bg-destructive/10 hover:text-destructive'
                  : 'text-muted-foreground'
              )}
              type="button"
              aria-label="Clear filters"
              title="Clear filters"
              disabled={!browse.hasBrowseFilters}
              onclick={() => browse.clearBrowseFilters()}
            >
              <FilterX size={16} aria-hidden="true" />
            </Button>
          </div>
          <div class="grid gap-3">
            <AdminFilterBar>
              <AdminFilterBarSearch
                label="Title"
                bind:value={browse.browseTitle}
                placeholder="Search title"
                class="w-[220px]"
              />
              <AdminFilterBarSelect
                label="Status"
                bind:value={browse.browseStatus}
                placeholder="Any"
                class="w-[180px]"
                options={[
                  { value: 'pending', label: 'Pending' },
                  { value: 'parsing', label: 'Parsing' },
                  { value: 'embedding', label: 'Embedding' },
                  { value: 'ready', label: 'Ready' },
                  { value: 'failed', label: 'Failed' }
                ]}
              />
              <AdminFilterBarSelect
                label="Owner"
                bind:value={browse.browseOwnerKind}
                placeholder="Any"
                class="w-[180px]"
                onValueChange={() => browse.handleBrowseOwnerKindChange()}
                options={[
                  { value: 'system', label: 'System' },
                  { value: 'character', label: 'Character' },
                  { value: 'user', label: 'User' }
                ]}
              />
            </AdminFilterBar>
            <div class="flex flex-wrap items-end gap-3">
              {#if browse.browseOwnerKind === 'character'}
                <label class={KNOWLEDGE_FIELD_LABEL}>
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
                  <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={browse.browseOwnerId}>
                    {#each options.characters as character (character.id)}
                      <option value={String(character.id)}>{character.name} ({character.id})</option>
                    {/each}
                  </select>
                </label>
              {:else if browse.browseOwnerKind === 'user'}
                <label class={KNOWLEDGE_FIELD_LABEL}>
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
                  <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={browse.browseOwnerId}>
                    {#each options.users as user (user.id)}
                      <option value={String(user.id)}>{user.name} ({user.id})</option>
                    {/each}
                  </select>
                </label>
              {/if}
            </div>
            <div class="flex flex-wrap items-end gap-3">
              <label class={KNOWLEDGE_FIELD_LABEL}>
                <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
                <CreatableCategorySelect
                  bind:value={browse.browseCategoryId}
                  options={options.topCategories}
                  placeholder="Any"
                  searchPlaceholder="Search or create category…"
                  creating={options.creatingCategory}
                  onSelect={() => {
                    browse.browseSubcategoryId = '';
                  }}
                  onCreate={(name) => options.upsertCategoryByName(name, null)}
                />
              </label>
              <label class={KNOWLEDGE_FIELD_LABEL}>
                <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
                <CreatableCategorySelect
                  bind:value={browse.browseSubcategoryId}
                  options={browse.browseSubcategories}
                  placeholder="Any"
                  searchPlaceholder="Search or create subcategory…"
                  disabled={!browse.browseCategoryId}
                  creating={options.creatingSubcategory}
                  onCreate={(name) => options.upsertCategoryByName(name, optionalInt(browse.browseCategoryId))}
                />
              </label>
              <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
                <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
                <CreatableTagsSelect
                  bind:selected={browse.browseTags}
                  options={options.tags}
                  creating={options.creatingTag}
                  onCreate={options.upsertTag}
                />
              </label>
            </div>
          </div>
        </div>

        <AdminMasterDetail layout="stack" detailOpen={Boolean(browse.activeDocument)}>
          {#snippet list()}
            {#if browse.documents.length === 0}
              <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No documents</div>
            {:else}
              <AdminTableShell stickyHead maxBodyHeight="280px">
                <thead class={KNOWLEDGE_TABLE_HEAD}>
                  <tr>
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
                    <th class="w-10 px-2 py-2" aria-label="Actions"><span class="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {#each browse.sortedDocuments as doc (doc.id)}
                    <tr
                      class={cnKnowledgeBrowseDocRow(doc.id === browse.activeDocumentId)}
                      onclick={() => void browse.openDocument(doc.id)}
                    >
                    <td class="max-w-[280px] truncate px-3 py-2 font-medium">
                      <span class="inline-flex min-w-0 items-center gap-1.5">
                        <button
                          type="button"
                          class="shrink-0 rounded-sm p-0.5 text-primary/85 hover:bg-primary/10 hover:text-primary"
                          aria-label={`Preview ${doc.title}`}
                          onclick={(event) => {
                            event.stopPropagation();
                            openDocumentPreview(doc);
                          }}
                        >
                          <Search size={14} aria-hidden="true" />
                        </button>
                        <span class="truncate">{doc.title}</span>
                      </span>
                    </td>
                    <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">{doc.owner_kind}/{doc.owner_id}</td>
                    <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">
                      {options.categoryLabel(doc.category_id)}{doc.subcategory_id ? ` > ${options.categoryLabel(doc.subcategory_id)}` : ''}
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
                    <td class="px-3 py-2 text-muted-foreground">{doc.chunk_count ?? '—'}</td>
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
                    <td class="px-2 py-2">
                      <button
                        type="button"
                        class="rounded-sm p-0.5 text-destructive hover:bg-destructive/10"
                        aria-label={`Delete document entry (${doc.title})`}
                        title={`Delete document entry (${doc.title})`}
                        onclick={(event) => {
                          event.stopPropagation();
                          openDeleteDialog(doc);
                        }}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                  {/each}
                </tbody>
              </AdminTableShell>
            {/if}
          {/snippet}
          {#snippet detail()}
            {#if browse.activeDocument}
              {@const doc = browse.activeDocument}
              <div class={KNOWLEDGE_METADATA_SHELL}>
            <div class="grid gap-1">
              <div class="font-sans text-sm font-medium">Document Actions</div>
              <p class="font-sans text-xs leading-relaxed text-muted-foreground">
                <span class="font-medium text-foreground">{doc.title}</span>
                <span class="mx-1.5 select-none text-border" aria-hidden="true">·</span>
                <span class="font-mono">{fileName(doc.source_uri)}</span>
                <span class="mx-1.5 select-none text-border" aria-hidden="true">·</span>
                <span class="break-all font-mono">{doc.source_uri}</span>
              </p>
            </div>
            <div class="grid gap-3">
              <div class="flex flex-wrap items-end gap-3">
                <label class={KNOWLEDGE_FIELD_LABEL}>
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
                  <select
                    class={cn(KNOWLEDGE_SELECT, 'w-[180px]')}
                    value={doc.owner_kind}
                    onchange={(event) => {
                      browse.updateActiveDocumentDraft({ owner_kind: event.currentTarget.value });
                      browse.handleDetailOwnerKindChange();
                    }}
                  >
                    <option value="system">System</option>
                    <option value="character">Character</option>
                    <option value="user">User</option>
                  </select>
                </label>
                {#if doc.owner_kind === 'character'}
                  <label class={KNOWLEDGE_FIELD_LABEL}>
                    <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
                    <select
                      class={cn(KNOWLEDGE_SELECT, 'w-[220px]')}
                      value={doc.owner_id}
                      onchange={(event) => browse.updateActiveDocumentDraft({ owner_id: event.currentTarget.value })}
                    >
                      {#each options.characters as character (character.id)}
                        <option value={String(character.id)}>{character.name} ({character.id})</option>
                      {/each}
                    </select>
                  </label>
                {:else if doc.owner_kind === 'user'}
                  <label class={KNOWLEDGE_FIELD_LABEL}>
                    <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
                    <select
                      class={cn(KNOWLEDGE_SELECT, 'w-[220px]')}
                      value={doc.owner_id}
                      onchange={(event) => browse.updateActiveDocumentDraft({ owner_id: event.currentTarget.value })}
                    >
                      {#each options.users as user (user.id)}
                        <option value={String(user.id)}>{user.name} ({user.id})</option>
                      {/each}
                    </select>
                  </label>
                {/if}
                <label class={KNOWLEDGE_FIELD_LABEL}>
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
                  <CreatableCategorySelect
                    bind:value={browse.detailCategoryId}
                    options={options.topCategories}
                    placeholder="None"
                    searchPlaceholder="Search or create category…"
                    creating={options.creatingCategory}
                    onSelect={() => {
                      browse.detailSubcategoryId = '';
                    }}
                    onCreate={(name) => options.upsertCategoryByName(name, null)}
                  />
                </label>
                <label class={KNOWLEDGE_FIELD_LABEL}>
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
                  <CreatableCategorySelect
                    bind:value={browse.detailSubcategoryId}
                    options={browse.activeDocumentSubcategories}
                    placeholder="None"
                    searchPlaceholder="Search or create subcategory…"
                    disabled={!browse.detailCategoryId}
                    creating={options.creatingSubcategory}
                    onCreate={(name) => options.upsertCategoryByName(name, optionalInt(browse.detailCategoryId))}
                  />
                </label>
                <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
                  <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
                  <CreatableTagsSelect
                    bind:selected={browse.detailTags}
                    options={options.tags}
                    creating={options.creatingTag}
                    onCreate={options.upsertTag}
                  />
                </label>
              </div>
              <div class="flex flex-wrap justify-end gap-2">
                <Button class="h-8" variant="outline" onclick={() => void handleUpdateMetadata()}>Update metadata</Button>
                <Button class="h-8" variant="outline" onclick={() => void browse.reingestActiveDocument()} disabled={ingest.ingesting}>
                  Re-ingest
                </Button>
              </div>
            </div>
              </div>
            {/if}
          {/snippet}
        </AdminMasterDetail>
      </div>
    {/if}
  </div>

  <div class={KNOWLEDGE_SECTION_CARD}>
    <div class="mb-3 flex min-w-0 items-center gap-2 border-b border-border pb-3">
      <Database size={17} class="shrink-0 text-muted-foreground" />
      <h3 class="flex min-w-0 flex-1 items-center gap-2 font-sans text-base">
        <span class={cn(KNOWLEDGE_SECTION_TITLE, 'shrink-0')}>Document Chunks:</span>
        {#if browse.activeDocument}
          {@const doc = browse.activeDocument}
          <span
            class="inline-flex min-w-0 flex-1 items-baseline gap-x-2 overflow-hidden text-sm font-normal text-muted-foreground"
            title={doc.source_uri}
          >
            <span class="truncate font-medium text-foreground">{doc.title}</span>
            <span class="shrink-0 select-none text-border" aria-hidden="true">·</span>
            <span class="max-w-[10rem] truncate font-mono text-xs">{fileName(doc.source_uri)}</span>
            <span class="shrink-0 select-none text-border" aria-hidden="true">·</span>
            <span
              class="inline-flex min-w-0 flex-[1.75] items-baseline gap-x-3 overflow-hidden text-xs text-muted-foreground"
              title={documentMetadataTitleAttr(doc, browse.detailTags, options.categoryLabel)}
            >
              <span class="shrink-0 whitespace-nowrap">
                <span class="font-semibold text-foreground">Owner:</span>
                {doc.owner_kind}/{doc.owner_id}
              </span>
              <span class="shrink-0 whitespace-nowrap">
                <span class="font-semibold text-foreground">Category:</span>
                {documentCategoryDisplay(doc, options.categoryLabel)}
              </span>
              <span class="min-w-0 truncate">
                <span class="font-semibold text-foreground">Tags:</span>
                {browse.detailTags.length > 0 ? browse.detailTags.join(', ') : '—'}
              </span>
            </span>
            <span class="shrink-0 select-none text-border" aria-hidden="true">·</span>
            <span class="shrink-0 font-mono text-xs">{documentMimeLabel(doc)}</span>
            <span class="shrink-0 select-none text-border" aria-hidden="true">·</span>
            <span class="shrink-0 tabular-nums">{formatBytes(doc.size_bytes)}</span>
            <span class="shrink-0 select-none text-border" aria-hidden="true">·</span>
            <span class="shrink-0 whitespace-nowrap tabular-nums">{formatChatTimestamp(doc.ingested_at)}</span>
          </span>
        {:else}
          <span class="text-sm font-normal text-muted-foreground">…</span>
        {/if}
      </h3>
      {#if browse.activeDocument}
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0 text-muted-foreground hover:text-foreground"
          type="button"
          aria-label="Test query against this document"
          title="Test query against this document"
          onclick={() => ctl.openAskForDocument(browse.activeDocument!)}
        >
          <Search size={16} aria-hidden="true" />
        </Button>
      {/if}
      <Button
        variant="ghost"
        size="icon"
        class="size-8 shrink-0 text-muted-foreground hover:text-foreground"
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
      <Badge class="shrink-0" variant="outline">
        {browse.chunks.length}{#if browse.activeDocument?.chunk_count != null && browse.activeDocument.chunk_count !== browse.chunks.length}
          / {browse.activeDocument.chunk_count}{/if}
      </Badge>
    </div>
    <div class="rounded-md border">
      {#if browse.chunks.length === 0}
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
</section>

<KnowledgeFilePreviewDialog bind:open={previewOpen} file={previewFile} />

<Dialog.Root bind:open={deleteOpen}>
  <Dialog.Content showCloseButton={!deleting}>
    <Dialog.Header>
      <Dialog.Title class="break-words">
        Delete document entry ({deleteTarget?.title ?? 'unknown'})?
      </Dialog.Title>
      <Dialog.Description>
        This removes the document entry and all indexed chunks from the knowledge base. The source file on disk
        is not deleted.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" disabled={deleting} onclick={() => (deleteOpen = false)}>Cancel</Button>
      <Button variant="destructive" disabled={deleting} onclick={() => void confirmDeleteDocument()}>
        Delete Document
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<ToastHost toast={toasts.toast} />
