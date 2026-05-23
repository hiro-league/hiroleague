<script lang="ts">
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { prepareChunkMarkdownForPreview } from '$lib/features/knowledge/shared/chunk-markdown';
  import { cn } from '$lib/utils';

  let {
    markdown,
    class: className = ''
  }: {
    markdown: string | null | undefined;
    class?: string;
  } = $props();

  const prepared = $derived(prepareChunkMarkdownForPreview(markdown));
</script>

<MarkdownPreview
  markdown={prepared}
  compact
  class={cn(
    '[&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_h4]:text-sm [&_h5]:text-sm [&_h6]:text-sm',
    '[&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h4]:font-semibold',
    '[&_h1]:leading-snug [&_h2]:leading-snug [&_h3]:leading-snug [&_h4]:leading-snug',
    className
  )}
/>
