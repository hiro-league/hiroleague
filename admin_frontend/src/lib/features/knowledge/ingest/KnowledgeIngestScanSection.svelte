<script lang="ts">
  import {
    Ban,
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
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import type { KnowledgeScannedFile } from '$lib/api/knowledge';
  import type { KnowledgeIngestModel } from '$lib/features/knowledge/state/knowledge-ingest.svelte';
  import { fileName, formatBytes, relativeFolderPath } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_TABLE_HEAD
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  type Props = {
    ingest: KnowledgeIngestModel;
    onPreviewFile: (file: KnowledgeScannedFile) => void;
  };

  let { ingest, onPreviewFile }: Props = $props();

  let selectAllCheckboxEl = $state<HTMLInputElement | null>(null);

  const selectAllCheckboxTooltip = $derived(
    ingest.supportedFiles.length === 0
      ? 'No selectable files'
      : ingest.allSupportedSelected
        ? 'Deselect all files'
        : ingest.allReadySelected
          ? 'Select ready and indexed files'
          : 'Select all ready files'
  );

  $effect(() => {
    if (selectAllCheckboxEl) {
      selectAllCheckboxEl.indeterminate = ingest.someSupportedSelected;
    }
  });

  const fileSort = $derived(ingest.fileSort);
</script>

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

    {#if ingest.files.length === 0}
      {#if ingest.folder.trim() && !ingest.hasScanned}
        <div class="flex flex-col items-center gap-2 py-2 text-center">
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
        <div class="flex min-h-[290px] items-center justify-center px-3 py-8 text-center font-sans text-sm text-muted-foreground">
          {ingest.folder.trim() ? 'No scan results' : 'Enter a folder path to scan'}
        </div>
      {/if}
    {:else if ingest.visibleFiles.length === 0}
      <div class="flex min-h-[290px] items-center justify-center px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        No supported files in this folder
      </div>
    {:else}
      <AdminTableShell stickyHead maxBodyHeight="400px">
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
                onclick={(event) => {
                  event.preventDefault();
                  ingest.cycleSelectAll();
                }}
              />
            </th>
            <AdminTableHeaderCell column="filename" sort={fileSort}>Filename</AdminTableHeaderCell>
            <AdminTableHeaderCell column="relative_path" sort={fileSort}>Relative path</AdminTableHeaderCell>
            <AdminTableHeaderCell column="size" sort={fileSort}>Size</AdminTableHeaderCell>
            <AdminTableHeaderCell column="ext" sort={fileSort}>Ext</AdminTableHeaderCell>
            <AdminTableHeaderCell column="state" sort={fileSort}>State</AdminTableHeaderCell>
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
                    onclick={() => onPreviewFile(file)}
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
      </AdminTableShell>
    {/if}
    {#if ingest.supportedFiles.length > 0}
      <div class="font-sans text-xs text-muted-foreground">{ingest.supportedFiles.length} markdown files</div>
    {/if}
  </div>
</section>
