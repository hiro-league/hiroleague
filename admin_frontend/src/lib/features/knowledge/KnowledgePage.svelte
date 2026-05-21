<script lang="ts">
  import { onMount } from 'svelte';
  import {
    Check,
    Database,
    FileText,
    FolderSearch,
    LoaderCircle,
    RefreshCw,
    Search
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import {
    getKnowledgeDocument,
    getKnowledgeJob,
    ingestKnowledge,
    listKnowledgeDocuments,
    scanKnowledgeFolder,
    searchKnowledge,
    type KnowledgeChunk,
    type KnowledgeDocument,
    type KnowledgeIngestMetadata,
    type KnowledgeJobData,
    type KnowledgeScannedFile,
    type KnowledgeSearchHit
  } from '$lib/api/knowledge';
  import { cn } from '$lib/utils';

  type TabId = 'ingest' | 'ask' | 'browse';

  let activeTab = $state<TabId>('ingest');
  let folder = $state('');
  let query = $state('');
  let tagsText = $state('');
  let ownerKind = $state<KnowledgeIngestMetadata['owner_kind']>('system');
  let ownerId = $state('0');
  let categoryId = $state('');
  let subcategoryId = $state('');
  let scanning = $state(false);
  let ingesting = $state(false);
  let searching = $state(false);
  let loadingDocs = $state(false);
  let error = $state<string | null>(null);
  let files = $state<KnowledgeScannedFile[]>([]);
  let selected = $state<Record<string, boolean>>({});
  let job = $state<KnowledgeJobData | null>(null);
  let documents = $state<KnowledgeDocument[]>([]);
  let activeDocumentId = $state<string | null>(null);
  let chunks = $state<KnowledgeChunk[]>([]);
  let hits = $state<KnowledgeSearchHit[]>([]);

  const selectedPaths = $derived(files.filter((file) => selected[file.path]).map((file) => file.path));
  const supportedFiles = $derived(files.filter((file) => file.supported));
  const activeDocument = $derived(documents.find((doc) => doc.id === activeDocumentId) ?? null);

  const tabs: { id: TabId; label: string }[] = [
    { id: 'ingest', label: 'Ingest' },
    { id: 'ask', label: 'Ask' },
    { id: 'browse', label: 'Browse' }
  ];

  function formatBytes(value: number) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  function tagList() {
    return tagsText
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  function optionalInt(value: string) {
    const trimmed = value.trim();
    return trimmed ? Number.parseInt(trimmed, 10) : null;
  }

  function metadata(): KnowledgeIngestMetadata {
    return {
      owner_kind: ownerKind,
      owner_id: ownerId.trim() || (ownerKind === 'system' ? '0' : ''),
      category_id: optionalInt(categoryId),
      subcategory_id: optionalInt(subcategoryId),
      tags: tagList()
    };
  }

  async function loadDocuments() {
    loadingDocs = true;
    try {
      const payload = await listKnowledgeDocuments();
      documents = payload.data.documents;
      if (!activeDocumentId && documents[0]) {
        await openDocument(documents[0].id);
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load documents.';
    } finally {
      loadingDocs = false;
    }
  }

  async function scan() {
    if (!folder.trim()) return;
    scanning = true;
    error = null;
    try {
      const payload = await scanKnowledgeFolder(folder.trim(), true);
      files = payload.data.files;
      selected = Object.fromEntries(
        payload.data.files.filter((file) => file.supported && !file.already_ingested).map((file) => [file.path, true])
      );
    } catch (err) {
      error = err instanceof Error ? err.message : 'Folder scan failed.';
    } finally {
      scanning = false;
    }
  }

  async function ingestSelected() {
    if (!selectedPaths.length) return;
    ingesting = true;
    error = null;
    try {
      const payload = await ingestKnowledge(selectedPaths, metadata());
      job = payload.data;
      await pollJob(payload.data.job_id);
      await loadDocuments();
      await scan();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Ingest failed.';
    } finally {
      ingesting = false;
    }
  }

  async function pollJob(jobId: string) {
    for (let i = 0; i < 240; i += 1) {
      const payload = await getKnowledgeJob(jobId);
      job = payload.data;
      if (payload.data.status !== 'running') return;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
  }

  async function runSearch() {
    if (!query.trim()) return;
    searching = true;
    error = null;
    try {
      const payload = await searchKnowledge(query.trim(), 10);
      hits = payload.data.hits;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Search failed.';
    } finally {
      searching = false;
    }
  }

  async function openDocument(documentId: string) {
    activeDocumentId = documentId;
    try {
      const payload = await getKnowledgeDocument(documentId);
      chunks = payload.data.chunks;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load document.';
    }
  }

  onMount(() => {
    void loadDocuments();
  });
</script>

<svelte:head>
  <title>Knowledge - Hiro Admin</title>
</svelte:head>

<div class="grid gap-5">
  <section class="grid gap-3">
    <div class="flex flex-wrap items-center gap-3">
      <div class="grid size-10 place-items-center rounded-md border bg-card text-primary">
        <Database size={19} />
      </div>
      <div>
        <h2 class="font-sans text-2xl font-semibold">Knowledge</h2>
        <p class="font-sans text-sm text-muted-foreground">Markdown ingest and vector search</p>
      </div>
      <Button class="ml-auto" variant="outline" onclick={() => void loadDocuments()} disabled={loadingDocs}>
        <RefreshCw size={16} class={cn(loadingDocs && 'animate-spin')} />
        Refresh
      </Button>
    </div>
    <div class="flex flex-wrap gap-2 border-b">
      {#each tabs as tab (tab.id)}
        <button
          class={cn(
            'border-b-2 border-transparent px-3 py-2 font-sans text-sm font-medium text-muted-foreground',
            activeTab === tab.id && 'border-primary text-foreground'
          )}
          type="button"
          onclick={() => {
            activeTab = tab.id;
          }}
        >
          {tab.label}
        </button>
      {/each}
    </div>
    {#if error}
      <div class="rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
        {error}
      </div>
    {/if}
  </section>

  {#if activeTab === 'ingest'}
    <section class="rounded-md border bg-card p-4 shadow-sm">
      <div class="grid gap-4">
        <div class="grid gap-3 xl:grid-cols-[minmax(260px,1fr)_180px_150px_150px_180px]">
          <label class="grid gap-1 font-sans text-sm">
            <span class="font-medium">Folder</span>
            <input
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={folder}
              placeholder="D:\projects\hiroleague\docs"
            />
          </label>
          <label class="grid gap-1 font-sans text-sm">
            <span class="font-medium">Owner</span>
            <select
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={ownerKind}
              onchange={() => {
                if (ownerKind === 'system') ownerId = '0';
              }}
            >
              <option value="system">System</option>
              <option value="character">Character</option>
              <option value="user">User</option>
            </select>
          </label>
          <label class="grid gap-1 font-sans text-sm">
            <span class="font-medium">Owner ID</span>
            <input
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={ownerId}
            />
          </label>
          <label class="grid gap-1 font-sans text-sm">
            <span class="font-medium">Category ID</span>
            <input
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={categoryId}
              inputmode="numeric"
            />
          </label>
          <label class="grid gap-1 font-sans text-sm">
            <span class="font-medium">Subcategory ID</span>
            <input
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={subcategoryId}
              inputmode="numeric"
            />
          </label>
        </div>

        <div class="flex flex-wrap items-end gap-3">
          <label class="grid min-w-[240px] flex-1 gap-1 font-sans text-sm">
            <span class="font-medium">Tags</span>
            <input
              class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              bind:value={tagsText}
              placeholder="docs, phase1"
            />
          </label>
          <Button onclick={() => void scan()} disabled={scanning || !folder.trim()}>
            {#if scanning}
              <LoaderCircle size={16} class="animate-spin" />
            {:else}
              <FolderSearch size={16} />
            {/if}
            Scan
          </Button>
          <Button
            variant="outline"
            onclick={() => void ingestSelected()}
            disabled={ingesting || selectedPaths.length === 0}
          >
            {#if ingesting}
              <LoaderCircle size={16} class="animate-spin" />
            {:else}
              <Check size={16} />
            {/if}
            Ingest {selectedPaths.length}
          </Button>
        </div>

        {#if job}
          <div class="flex flex-wrap items-center gap-2 font-sans text-sm">
            <Badge variant={job.status === 'completed' ? 'success' : job.status === 'failed' ? 'destructive' : 'outline'}>
              {job.status}
            </Badge>
            <span class="text-muted-foreground">
              {job.totals.ingested ?? 0} ingested, {job.totals.skipped ?? 0} skipped, {job.totals.chunks ?? 0} chunks
            </span>
          </div>
        {/if}

        <div class="max-h-[520px] overflow-auto rounded-md border">
          {#if files.length === 0}
            <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No scan results</div>
          {:else}
            <table class="w-full text-left font-sans text-sm">
              <thead class="sticky top-0 bg-muted text-xs uppercase text-muted-foreground">
                <tr>
                  <th class="w-10 px-3 py-2"></th>
                  <th class="px-3 py-2">File</th>
                  <th class="px-3 py-2">Size</th>
                  <th class="px-3 py-2">State</th>
                </tr>
              </thead>
              <tbody>
                {#each files as file (file.path)}
                  <tr class="border-t">
                    <td class="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${file.relative_path}`}
                        disabled={!file.supported}
                        checked={!!selected[file.path]}
                        onchange={(event) => {
                          selected = { ...selected, [file.path]: event.currentTarget.checked };
                        }}
                      />
                    </td>
                    <td class="max-w-[620px] truncate px-3 py-2" title={file.path}>{file.relative_path}</td>
                    <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">{formatBytes(file.size_bytes)}</td>
                    <td class="px-3 py-2">
                      <Badge variant={file.already_ingested ? 'outline' : file.supported ? 'success' : 'secondary'}>
                        {file.already_ingested ? 'indexed' : file.supported ? file.ext : 'blocked'}
                      </Badge>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </div>
        {#if supportedFiles.length > 0}
          <div class="font-sans text-xs text-muted-foreground">{supportedFiles.length} markdown files</div>
        {/if}
      </div>
    </section>
  {:else if activeTab === 'ask'}
    <section class="rounded-md border bg-card p-4 shadow-sm">
      <div class="flex flex-wrap items-end gap-3">
        <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
          <span class="font-medium">Search</span>
          <input
            class="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
            bind:value={query}
            onkeydown={(event) => {
              if (event.key === 'Enter') void runSearch();
            }}
          />
        </label>
        <Button onclick={() => void runSearch()} disabled={searching || !query.trim()}>
          {#if searching}
            <LoaderCircle size={16} class="animate-spin" />
          {:else}
            <Search size={16} />
          {/if}
          Search
        </Button>
      </div>
      <div class="mt-4 grid gap-3">
        {#if hits.length === 0}
          <div class="rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
            No search results
          </div>
        {:else}
          {#each hits as hit (hit.point_id)}
            <button
              class="grid gap-2 rounded-md border bg-background p-3 text-left transition-colors hover:border-primary/40"
              type="button"
              onclick={() => {
                activeTab = 'browse';
                void openDocument(hit.document_id);
              }}
            >
              <div class="flex items-center gap-2">
                <FileText size={16} />
                <strong class="min-w-0 truncate font-sans text-sm">{hit.title}</strong>
                <Badge class="ml-auto" variant="outline">{hit.score.toFixed(3)}</Badge>
              </div>
              {#if hit.heading_path}
                <div class="truncate font-sans text-xs text-muted-foreground">{hit.heading_path}</div>
              {/if}
              <p class="line-clamp-3 font-sans text-sm text-muted-foreground">{hit.text}</p>
            </button>
          {/each}
        {/if}
      </div>
    </section>
  {:else}
    <section class="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
      <div class="rounded-md border bg-card p-4 shadow-sm">
        <div class="mb-3 flex items-center gap-2">
          <FileText size={17} />
          <h3 class="font-sans text-base font-semibold">Documents</h3>
          <Badge class="ml-auto" variant="outline">{documents.length}</Badge>
        </div>
        <div class="max-h-[640px] overflow-auto rounded-md border">
          {#if documents.length === 0}
            <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No documents</div>
          {:else}
            {#each documents as doc (doc.id)}
              <button
                class={cn(
                  'grid w-full gap-1 border-t px-3 py-2 text-left first:border-t-0 hover:bg-muted/50',
                  doc.id === activeDocumentId && 'bg-primary/10'
                )}
                type="button"
                onclick={() => void openDocument(doc.id)}
              >
                <span class="truncate font-sans text-sm font-medium">{doc.title}</span>
                <span class="font-sans text-xs text-muted-foreground">
                  {doc.chunk_count} chunks - {formatBytes(doc.size_bytes)}
                </span>
              </button>
            {/each}
          {/if}
        </div>
      </div>

      <div class="rounded-md border bg-card p-4 shadow-sm">
        <div class="mb-3 flex items-center gap-2">
          <Database size={17} />
          <h3 class="min-w-0 truncate font-sans text-base font-semibold">
            {activeDocument?.title ?? 'Chunks'}
          </h3>
          <Badge class="ml-auto" variant="outline">{chunks.length}</Badge>
        </div>
        <div class="max-h-[640px] overflow-auto rounded-md border">
          {#if chunks.length === 0}
            <div class="px-3 py-8 text-center font-sans text-sm text-muted-foreground">No chunks</div>
          {:else}
            {#each chunks as chunk (chunk.point_id)}
              <article class="grid gap-2 border-t px-3 py-3 first:border-t-0">
                <div class="flex items-center gap-2">
                  <Badge variant="outline">#{chunk.ord}</Badge>
                  {#if chunk.heading_path}
                    <span class="min-w-0 truncate font-sans text-xs text-muted-foreground">{chunk.heading_path}</span>
                  {/if}
                </div>
                <p class="whitespace-pre-wrap font-sans text-sm leading-6 text-muted-foreground">{chunk.text}</p>
              </article>
            {/each}
          {/if}
        </div>
      </div>
    </section>
  {/if}
</div>
