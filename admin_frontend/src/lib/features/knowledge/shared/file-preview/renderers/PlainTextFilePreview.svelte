<script lang="ts">
  import type { KnowledgeFilePreviewData } from '../file-preview-types';

  let { preview }: { preview: KnowledgeFilePreviewData } = $props();
</script>

<pre class="m-0 whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">{preview.content}</pre>
