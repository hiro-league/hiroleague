<script lang="ts">
  import { cn } from '$lib/utils';
  import { renderSafeMarkdown } from '$lib/components/ui/markdown/markdown';

  let {
    markdown,
    class: className = '',
    /** Tighter typography for inline / read-only panels. */
    compact = false
  }: {
    markdown: string | null | undefined;
    class?: string;
    compact?: boolean;
  } = $props();

  const html = $derived(renderSafeMarkdown(markdown));
  const empty = $derived(!(markdown ?? '').trim());
</script>

{#if empty}
  <p class="m-0 font-sans text-sm italic text-muted-foreground">Nothing to preview yet.</p>
{:else}
  <div
    class={cn(
      'prose prose-sm max-w-none font-sans text-foreground dark:prose-invert',
      compact && 'leading-snug',
      'prose-headings:font-sans prose-headings:text-foreground prose-strong:text-foreground',
      'prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:text-foreground',
      className
    )}
  >
    {@html html}
  </div>
{/if}
