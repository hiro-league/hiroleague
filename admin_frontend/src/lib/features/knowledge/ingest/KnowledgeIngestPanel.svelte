<script lang="ts">
  import {
    ArrowDown,
    ArrowUp,
    Ban,
    Check,
    CircleCheck,
    Eye,
    EyeOff,
    FileCheck,
    FolderOpen,
    FolderSearch,
    LoaderCircle,
    RefreshCw,
    Search
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import type { KnowledgeScannedFile } from '$lib/api/knowledge';
  import KnowledgeFilePreviewDialog from '$lib/features/knowledge/shared/file-preview/KnowledgeFilePreviewDialog.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import { fileName, formatBytes, jobElapsed, optionalInt, relativeFolderPath, type ScannedFileSortColumn } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SELECT,
    KNOWLEDGE_TABLE,
    KNOWLEDGE_TABLE_HEAD
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ingest = $derived(ctl.ingest);
  const options = $derived(ctl.options);

  let selectAllCheckboxEl = $state<HTMLInputElement | null>(null);
  let previewOpen = $state(false);
  let previewFile = $state<KnowledgeScannedFile | null>(null);

  function openFilePreview(file: KnowledgeScannedFile) {
    previewFile = file;
    previewOpen = true;
  }

  const selectAllCheckboxTooltip = $derived(
    ingest.supportedFiles.length === 0
      ? 'No selectable files'
      : ingest.allSupportedSelected
        ? 'Deselect all files'
        : 'Select all files'
  );

  $effect(() => {
    if (selectAllCheckboxEl) {
      selectAllCheckboxEl.indeterminate = ingest.someSupportedSelected;
    }
  });

  function fileSortAria(column: ScannedFileSortColumn): 'ascending' | 'descending' | 'none' {
    if (ingest.fileSortColumn !== column) return 'none';
    return ingest.fileSortDirection === 'asc' ? 'ascending' : 'descending';
  }
</script>

{#snippet sortableHeader(column: ScannedFileSortColumn, label: string)}
  <th class="px-3 py-2" aria-sort={fileSortAria(column)}>
    <button
      type="button"
      class="inline-flex items-center gap-1 font-inherit uppercase hover:text-foreground"
      onclick={() => ingest.toggleFileSort(column)}
    >
      {label}
      {#if ingest.fileSortColumn === column}
        {#if ingest.fileSortDirection === 'asc'}
          <ArrowUp size={12} aria-hidden="true" />
        {:else}
          <ArrowDown size={12} aria-hidden="true" />
        {/if}
      {/if}
    </button>
  </th>
{/snippet}

<section class={KNOWLEDGE_SECTION_CARD}>
  <div class="grid gap-4">
    <div class={KNOWLEDGE_FIELD_LABEL}>
      <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Folder</span>
      <span class="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          class="relative z-10 shrink-0"
          disabled={!ingest.folder.trim()}
          onclick={() => void ingest.openIngestFolder()}
          title={ingest.folder.trim() ? `Open folder: ${ingest.folder.trim()}` : 'Select a folder to open in Explorer'}
          aria-label={ingest.folder.trim() ? `Open folder: ${ingest.folder.trim()}` : 'Open folder in system file manager'}
        >
          <FolderOpen size={16} />
        </Button>
        <label class="block min-w-[300px] flex-1">
          <input
            class={cn(KNOWLEDGE_INPUT, 'w-full')}
            bind:value={ingest.folder}
            placeholder="Path to folder to scan"
            oninput={ingest.onFolderChange}
            onblur={ingest.onFolderBlur}
          />
        </label>
        <Button type="button" variant="outline" onclick={() => void ingest.browseFolder()} disabled={ingest.pickingFolder}>
          {#if ingest.pickingFolder}
            <LoaderCircle size={16} class="animate-spin" />
          {:else}
            <FolderSearch size={16} />
          {/if}
          Browse
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={ingest.showOnlySupported ? 'Showing supported files only' : 'Showing all scanned files'}
          aria-pressed={ingest.showOnlySupported}
          title={ingest.showOnlySupported
            ? 'Showing supported files only — click to show all files'
            : 'Showing all files — click to show supported only'}
          disabled={!ingest.hasScanned || ingest.files.length === 0}
          onclick={() => {
            ingest.showOnlySupported = !ingest.showOnlySupported;
          }}
        >
          {#if ingest.showOnlySupported}
            <Eye size={16} />
          {:else}
            <EyeOff size={16} />
          {/if}
        </Button>
        {#if ingest.folder.trim() && ingest.hasScanned}
          <Button variant="outline" onclick={() => void ingest.scan()} disabled={ingest.scanning}>
            {#if ingest.scanning}
              <LoaderCircle size={16} class="animate-spin" />
            {:else}
              <RefreshCw size={16} />
            {/if}
            Re-Scan
          </Button>
        {/if}
      </span>
    </div>

    <div class="h-[290px] overflow-auto rounded-md border">
      {#if ingest.files.length === 0}
        {#if ingest.folder.trim() && !ingest.hasScanned}
          <div class="flex h-full min-h-[290px] flex-col items-center justify-center gap-3 px-3 py-8 text-center">
            {#if ingest.scanning}
              <LoaderCircle size={24} class="animate-spin text-muted-foreground" />
              <p class="font-sans text-sm text-muted-foreground">Scanning folder…</p>
            {:else}
              <Button onclick={() => void ingest.scan()}>
                <FolderSearch size={16} />
                Scan folder for supported formats
              </Button>
            {/if}
          </div>
        {:else}
          <div class="flex h-full min-h-[290px] items-center justify-center px-3 py-8 text-center font-sans text-sm text-muted-foreground">
            {ingest.folder.trim() ? 'No scan results' : 'Enter a folder path to scan'}
          </div>
        {/if}
      {:else if ingest.visibleFiles.length === 0}
        <div class="flex h-full min-h-[290px] items-center justify-center px-3 py-8 text-center font-sans text-sm text-muted-foreground">
          No supported files in this folder
        </div>
      {:else}
        <table class={KNOWLEDGE_TABLE}>
          <thead class={KNOWLEDGE_TABLE_HEAD}>
            <tr>
              <th class="w-10 px-3 py-2">
                <input
                  bind:this={selectAllCheckboxEl}
                  type="checkbox"
                  aria-label={selectAllCheckboxTooltip}
                  title={selectAllCheckboxTooltip}
                  disabled={ingest.supportedFiles.length === 0}
                  checked={ingest.allSupportedSelected}
                  onchange={ingest.toggleSelectAllSupported}
                />
              </th>
              {@render sortableHeader('filename', 'Filename')}
              {@render sortableHeader('relative_path', 'Relative path')}
              {@render sortableHeader('size', 'Size')}
              {@render sortableHeader('ext', 'Ext')}
              {@render sortableHeader('state', 'State')}
            </tr>
          </thead>
          <tbody>
            {#each ingest.sortedVisibleFiles as file (file.path)}
              <tr class="border-t" title={!file.supported ? 'Not yet supported' : file.path}>
                <td class="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${file.relative_path}`}
                    disabled={!file.supported}
                    checked={!!ingest.selected[file.path]}
                    onchange={(event) => {
                      ingest.toggleFileSelection(file.path, event.currentTarget.checked);
                    }}
                  />
                </td>
                <td class="max-w-[220px] truncate px-3 py-2 font-medium">
                  <span class="inline-flex min-w-0 items-center gap-1.5">
                    <button
                      type="button"
                      class="shrink-0 rounded-sm p-0.5 text-primary/85 hover:bg-primary/10 hover:text-primary"
                      aria-label={`Preview ${fileName(file.relative_path)}`}
                      onclick={() => openFilePreview(file)}
                    >
                      <Search size={14} aria-hidden="true" />
                    </button>
                    <span class="truncate">{fileName(file.relative_path)}</span>
                  </span>
                </td>
                <td class="max-w-[520px] truncate px-3 py-2 text-muted-foreground" title={relativeFolderPath(file.relative_path) || 'Scan root'}>
                  {relativeFolderPath(file.relative_path) || '—'}
                </td>
                <td class="whitespace-nowrap px-3 py-2 text-muted-foreground">{formatBytes(file.size_bytes)}</td>
                <td class="px-3 py-2">
                  <Badge variant={file.supported ? 'success' : 'secondary'}>{file.ext || 'none'}</Badge>
                </td>
                <td class="px-3 py-2">
                  <span class="inline-flex items-center gap-1.5">
                    {#if file.already_ingested}
                      <CircleCheck size={14} class="shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
                    {:else if file.supported}
                      <FileCheck size={14} class="shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
                    {:else}
                      <Ban size={14} class="shrink-0 text-destructive" aria-hidden="true" />
                    {/if}
                    <Badge variant={file.already_ingested ? 'outline' : file.supported ? 'success' : 'secondary'}>
                      {file.already_ingested ? 'indexed' : file.supported ? 'ready' : 'blocked'}
                    </Badge>
                  </span>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
    {#if ingest.supportedFiles.length > 0}
      <div class="font-sans text-xs text-muted-foreground">{ingest.supportedFiles.length} markdown files</div>
    {/if}

    <div class={KNOWLEDGE_METADATA_SHELL}>
      <div class="font-sans text-sm font-medium">Ingest metadata</div>
      <div class="grid gap-3">
        <div class="flex flex-wrap items-end gap-3">
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
            <select class={cn(KNOWLEDGE_SELECT, 'w-[180px]')} bind:value={ingest.ownerKind} onchange={ingest.handleOwnerKindChange}>
              <option value="system">System</option>
              <option value="character">Character</option>
              <option value="user">User</option>
            </select>
          </label>
          {#if ingest.ownerKind === 'character'}
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
              <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ingest.ownerId}>
                {#each options.characters as character (character.id)}
                  <option value={String(character.id)}>{character.name} ({character.id})</option>
                {/each}
              </select>
            </label>
          {:else if ingest.ownerKind === 'user'}
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
              <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ingest.ownerId}>
                {#each options.users as user (user.id)}
                  <option value={String(user.id)}>{user.name} ({user.id})</option>
                {/each}
              </select>
            </label>
          {/if}
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
            <CreatableCategorySelect
              bind:value={ingest.categoryId}
              options={options.topCategories}
              placeholder="None"
              searchPlaceholder="Search or create category…"
              creating={options.creatingCategory}
              onSelect={() => {
                ingest.subcategoryId = '';
              }}
              onCreate={(name) => options.upsertCategoryByName(name, null)}
            />
          </label>
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
            <CreatableCategorySelect
              bind:value={ingest.subcategoryId}
              options={ingest.subcategories}
              placeholder="None"
              searchPlaceholder="Search or create subcategory…"
              disabled={!ingest.categoryId}
              creating={options.creatingSubcategory}
              onCreate={(name) => options.upsertCategoryByName(name, optionalInt(ingest.categoryId))}
            />
          </label>
          <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
            <CreatableTagsSelect
              bind:selected={ingest.ingestTags}
              options={options.tags}
              creating={options.creatingTag}
              onCreate={options.upsertTag}
            />
          </label>
          <Button
            variant="outline"
            onclick={() => void ingest.ingestSelected()}
            disabled={ingest.ingesting || ingest.selectedPaths.length === 0 || (ingest.ownerKind !== 'system' && !ingest.ownerId)}
          >
            {#if ingest.ingesting}
              <LoaderCircle size={16} class="animate-spin" />
            {:else}
              <Check size={16} />
            {/if}
            Ingest {ingest.selectedPaths.length}
          </Button>
        </div>
      </div>
    </div>

    {#if ingest.job}
      <div class="grid gap-2 rounded-md border bg-background p-3 font-sans text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant={ingest.job.status === 'completed' ? 'success' : ingest.job.status === 'failed' ? 'destructive' : 'outline'}>
            {ingest.job.status}
          </Badge>
          <span class="text-muted-foreground">
            {ingest.job.totals.ingested ?? 0} ingested, {ingest.job.totals.skipped ?? 0} skipped, {ingest.job.totals.failed ?? 0} failed,
            {ingest.job.totals.chunks ?? 0} chunks
          </span>
          {#if ingest.currentJobRecord}
            <span class="text-xs text-muted-foreground">elapsed {jobElapsed(ingest.currentJobRecord.created_at)}</span>
          {/if}
          <span class="ml-auto text-xs text-muted-foreground">{ingest.jobDone}/{ingest.job.totals.requested ?? 0} files</span>
          <Button class="h-8" type="button" variant="outline" disabled title="Cancellation is documented but not implemented yet.">
            Cancel
          </Button>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-muted">
          <div class="h-full bg-primary transition-all" style={`width: ${ingest.jobPercent}%`}></div>
        </div>
        {#if ingest.job.in_flight?.length}
          <div class="truncate font-sans text-xs text-muted-foreground" title={ingest.job.in_flight.join(', ')}>
            Processing {ingest.job.in_flight.length} file(s): {ingest.job.in_flight.join(', ')}
          </div>
        {/if}
        {#if Object.keys(ingest.job.errors).length > 0}
          <details class="text-xs text-destructive">
            <summary>View errors</summary>
            <pre class="mt-2 whitespace-pre-wrap rounded-md bg-destructive/10 p-2">{JSON.stringify(ingest.job.errors, null, 2)}</pre>
          </details>
        {/if}
      </div>
    {/if}

    {#if ingest.recentJobs.length > 0}
      <div class="grid gap-2 rounded-md border bg-background p-3">
        <div class="font-sans text-sm font-medium">Recent jobs</div>
        <div class="h-[7rem] overflow-auto rounded-md border">
          <div class="grid gap-2 p-2">
            {#each ingest.recentJobs as item (item.id)}
              <div class="flex flex-wrap items-center gap-2 font-sans text-xs text-muted-foreground">
              <Badge variant={item.status === 'completed' ? 'success' : item.status === 'failed' ? 'destructive' : 'outline'}>
                {item.status}
              </Badge>
              <span>{formatChatTimestamp(item.created_at)}</span>
              <span>
                {item.totals.ingested ?? 0} ingested, {item.totals.skipped ?? 0} skipped,
                {item.totals.failed ?? 0} failed, {item.totals.chunks ?? 0} chunks
              </span>
              {#if item.status === 'failed'}
                <Button class="h-7" type="button" variant="outline" onclick={() => void ingest.retryJob(item)} disabled={ingest.ingesting}>
                  Retry
                </Button>
              {/if}
              {#if Object.keys(item.errors).length > 0}
                <Button
                  class="h-7"
                  type="button"
                  variant="outline"
                  onclick={() => ingest.toggleActiveErrorsJobId(item.id)}
                >
                  View errors
                </Button>
              {/if}
              {#if ingest.activeErrorsJobId === item.id}
                <details class="basis-full text-destructive" open>
                  <summary>Errors</summary>
                  <pre class="mt-2 whitespace-pre-wrap rounded-md bg-destructive/10 p-2">{JSON.stringify(item.errors, null, 2)}</pre>
                </details>
              {/if}
            </div>
          {/each}
          </div>
        </div>
      </div>
    {/if}
  </div>
</section>

<KnowledgeFilePreviewDialog bind:open={previewOpen} file={previewFile} />
