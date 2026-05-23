<script lang="ts">
  import type { KnowledgeFilePreviewData } from '../file-preview-types';

  let { preview }: { preview: KnowledgeFilePreviewData } = $props();
</script>

<div class="grid gap-2 font-sans text-sm text-muted-foreground">
  <p class="m-0">This file type cannot be previewed for ingest.</p>
  {#if preview.disabled_reason}
    <p class="m-0 rounded-md border bg-muted/40 px-3 py-2 text-xs text-foreground">{preview.disabled_reason}</p>
  {/if}
</div>
