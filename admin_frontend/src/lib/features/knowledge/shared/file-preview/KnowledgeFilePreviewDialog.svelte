<script lang="ts">
  import * as Dialog from '$lib/components/ui/dialog';
  import { previewKnowledgeFile, type KnowledgeScannedFile } from '$lib/api/knowledge';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { fileName } from '$lib/features/knowledge/shared/knowledge-pure';
  import KnowledgeFilePreviewMetrics from './KnowledgeFilePreviewMetrics.svelte';
  import type { KnowledgeFilePreviewData } from './file-preview-types';
  import MarkdownFilePreview from './renderers/MarkdownFilePreview.svelte';
  import PlainTextFilePreview from './renderers/PlainTextFilePreview.svelte';
  import UnsupportedFilePreview from './renderers/UnsupportedFilePreview.svelte';

  let {
    open = $bindable(false),
    file = null
  }: {
    open?: boolean;
    file?: KnowledgeScannedFile | null;
  } = $props();

  let preview = $state<KnowledgeFilePreviewData | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function loadPreview(target: KnowledgeScannedFile) {
    loading = true;
    error = null;
    preview = null;
    try {
      const payload = await previewKnowledgeFile(target.path);
      preview = payload.data;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load file preview.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (!open || !file) return;
    void loadPreview(file);
  });

  $effect(() => {
    if (open) return;
    preview = null;
    error = null;
    loading = false;
  });
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="flex h-[min(85vh,920px)] w-[50vw] max-w-[50vw] flex-col gap-0 overflow-hidden bg-background p-0 sm:max-w-[50vw]"
    showCloseButton={true}
  >
    <Dialog.Header class="shrink-0 border-b border-border/80 bg-muted/45 px-4 py-3.5 pr-12">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
          <Dialog.Title class="truncate font-sans text-lg font-semibold leading-tight">
            {file ? fileName(file.relative_path) : 'File preview'}
          </Dialog.Title>
          {#if file}
            <Dialog.Description class="mt-1 truncate font-sans text-xs text-muted-foreground">
              {file.relative_path}
            </Dialog.Description>
          {/if}
        </div>
        {#if preview && preview.supported}
          <KnowledgeFilePreviewMetrics
            class="shrink-0 pt-0.5"
            metrics={{
              line_count: preview.line_count,
              character_count: preview.character_count,
              estimated_tokens: preview.estimated_tokens
            }}
          />
        {/if}
      </div>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-auto bg-card px-4 py-3">
      {#if loading}
        <div class="grid h-full min-h-[240px] place-items-center">
          <InlineLoading label="Loading preview…" />
        </div>
      {:else if error}
        <InlineDestructiveAlert message={error} />
      {:else if preview}
        {#if preview.truncated}
          <p class="mb-3 font-sans text-xs text-amber-700 dark:text-amber-300">
            Preview truncated to the first 2 MB of this file.
          </p>
        {/if}
        {#if preview.format === 'markdown'}
          <MarkdownFilePreview {preview} />
        {:else if preview.format === 'plain-text'}
          <PlainTextFilePreview {preview} />
        {:else}
          <UnsupportedFilePreview {preview} />
        {/if}
      {/if}
    </div>
  </Dialog.Content>
</Dialog.Root>
