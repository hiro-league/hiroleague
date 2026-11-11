<script lang="ts">
  import { cn } from '$lib/utils';
  import { count } from '$kit/format/number';
  import type { FilePreviewMetrics } from './file-preview-types';

  let { metrics, class: className = '' }: { metrics: FilePreviewMetrics; class?: string } = $props();
</script>

<div
  class={cn(
    'flex flex-wrap justify-end gap-x-3 gap-y-1 font-sans text-xs tabular-nums text-muted-foreground',
    className
  )}
>
  <span>{count(metrics.line_count)} lines</span>
  <span>{count(metrics.character_count)} chars</span>
  <span>~{count(metrics.estimated_tokens)} tokens</span>
</div>
