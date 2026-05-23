<script lang="ts">
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import type { KnowledgeFilePreviewData } from '../file-preview-types';

  let { preview }: { preview: KnowledgeFilePreviewData } = $props();
</script>

<MarkdownPreview markdown={preview.content} class="pb-1" />
