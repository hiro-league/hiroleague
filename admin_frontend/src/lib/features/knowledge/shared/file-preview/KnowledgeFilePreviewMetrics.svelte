<script lang="ts">
  import { cn } from '$lib/utils';
  import type { FilePreviewMetrics } from './file-preview-types';

  let { metrics, class: className = '' }: { metrics: FilePreviewMetrics; class?: string } = $props();
</script>

<div
  class={cn(
    'flex flex-wrap justify-end gap-x-3 gap-y-1 font-sans text-xs tabular-nums text-muted-foreground',
    className
  )}
>
  <span>{metrics.line_count.toLocaleString()} lines</span>
  <span>{metrics.character_count.toLocaleString()} chars</span>
  <span>~{metrics.estimated_tokens.toLocaleString()} tokens</span>
</div>
