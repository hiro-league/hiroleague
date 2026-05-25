<script lang="ts">
  import { base } from '$app/paths';
  import {
    Ban,
    Check,
    ChevronRight,
    CircleCheck,
    ExternalLink,
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
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import type { KnowledgeScannedFile } from '$lib/api/knowledge';
  import KnowledgeFilePreviewDialog from '$lib/features/knowledge/shared/file-preview/KnowledgeFilePreviewDialog.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import { fileName, formatBytes, formatIngestHeaderSummary, formatJobTotalsSummary, formatRecentJobsHeaderSummary, jobElapsed, KNOWLEDGE_BROWSE_HREF, optionalInt, relativeFolderPath } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SECTION_TITLE,
    KNOWLEDGE_SELECT,
    KNOWLEDGE_TABLE_HEAD
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
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
  let recentJobsExpanded = $state(false);
  let ingestSectionExpanded = $state(false);

  const INGEST_BODY_ID = 'knowledge-ingest-section';
  const RECENT_JOBS_BODY_ID = 'knowledge-ingest-recent-jobs';

  function openFilePreview(file: KnowledgeScannedFile) {
    previewFile = file;
    previewOpen = true;
  }

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
  const ingestHeaderSummary = $derived(
    formatIngestHeaderSummary(ingest.selectedPaths.length, ingest.job?.status ?? null)
  );
  const recentJobsHeaderSummary = $derived(formatRecentJobsHeaderSummary(ingest.recentJobs));

  $effect(() => {
    if (ingest.ingesting || ingest.job?.status === 'running') {
      ingestSectionExpanded = true;
    }
  });
</script>

<section class="grid gap-4">
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
      </AdminTableShell>
    {/if}
    {#if ingest.supportedFiles.length > 0}
      <div class="font-sans text-xs text-muted-foreground">{ingest.supportedFiles.length} markdown files</div>
    {/if}
    </div>
  </section>

  <section class={KNOWLEDGE_SECTION_CARD}>
    <div class="grid gap-3">
      <div class="flex items-start justify-between gap-2">
        <button
          type="button"
          class="flex min-w-0 flex-1 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
          aria-expanded={ingestSectionExpanded}
          aria-controls={INGEST_BODY_ID}
          onclick={() => {
            ingestSectionExpanded = !ingestSectionExpanded;
          }}
        >
          <ChevronRight
            size={18}
            class={cn(
              'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
              ingestSectionExpanded && 'rotate-90'
            )}
            aria-hidden="true"
          />
          <span class={KNOWLEDGE_SECTION_TITLE}>Ingest</span>
        </button>
        {#if ingestHeaderSummary}
          <span class="shrink-0 text-right font-sans text-xs text-muted-foreground">{ingestHeaderSummary}</span>
        {/if}
      </div>
      <div id={INGEST_BODY_ID} class="grid gap-3" hidden={!ingestSectionExpanded}>
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
                {formatJobTotalsSummary(ingest.job.totals)}
              </span>
              {#if ingest.currentJobRecord}
                <span class="text-xs text-muted-foreground">elapsed {jobElapsed(ingest.currentJobRecord.created_at)}</span>
              {/if}
              <span class="ml-auto text-xs text-muted-foreground">{ingest.jobDone}/{ingest.job.totals.requested ?? 0} files</span>
              {#if ingest.job.status === 'running'}
                <Button class="h-8" type="button" variant="outline" disabled title="Cancellation is documented but not implemented yet.">
                  Cancel
                </Button>
              {:else if ingest.job.status === 'completed'}
                <a
                  class="inline-flex h-8 items-center gap-1 rounded-md border px-2 py-1 font-sans text-xs text-primary hover:bg-primary/5"
                  href={`${base}${KNOWLEDGE_BROWSE_HREF}`}
                  onclick={(event) => {
                    event.preventDefault();
                    void ctl.setActiveTab('browse');
                  }}
                >
                  View documents
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              {/if}
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
              <details class="text-xs">
                <summary class="text-destructive">View errors</summary>
                <InlineDestructiveAlert
                  class="mt-2 whitespace-pre-wrap font-mono text-xs"
                  message={JSON.stringify(ingest.job.errors, null, 2)}
                />
              </details>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  </section>

  {#if ingest.recentJobs.length > 0}
    <section class={KNOWLEDGE_SECTION_CARD}>
      <div class="grid gap-3">
        <div class="flex items-start justify-between gap-2">
          <button
            type="button"
            class="flex min-w-0 flex-1 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={recentJobsExpanded}
            aria-controls={RECENT_JOBS_BODY_ID}
            onclick={() => {
              recentJobsExpanded = !recentJobsExpanded;
            }}
          >
            <ChevronRight
              size={18}
              class={cn(
                'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
                recentJobsExpanded && 'rotate-90'
              )}
              aria-hidden="true"
            />
            <span class={KNOWLEDGE_SECTION_TITLE}>Recent jobs</span>
          </button>
          <span class="shrink-0 text-right font-sans text-xs text-muted-foreground">{recentJobsHeaderSummary}</span>
        </div>
        <div id={RECENT_JOBS_BODY_ID} class="grid gap-2" hidden={!recentJobsExpanded}>
          {#each ingest.recentJobs as item (item.id)}
            <div class="flex flex-wrap items-center gap-2 rounded-md border bg-background p-2 font-sans text-xs text-muted-foreground">
              <Badge variant={item.status === 'completed' ? 'success' : item.status === 'failed' ? 'destructive' : 'outline'}>
                {item.status}
              </Badge>
              <span>{formatChatTimestamp(item.created_at)}</span>
              <span>{formatJobTotalsSummary(item.totals)}</span>
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
                <details class="basis-full text-xs" open>
                  <summary class="text-destructive">Errors</summary>
                  <InlineDestructiveAlert
                    class="mt-2 whitespace-pre-wrap font-mono text-xs"
                    message={JSON.stringify(item.errors, null, 2)}
                  />
                </details>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    </section>
  {/if}
</section>

<KnowledgeFilePreviewDialog bind:open={previewOpen} file={previewFile} />
