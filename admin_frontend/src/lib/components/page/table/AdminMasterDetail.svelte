<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    detailOpen?: boolean;
    /** Side-by-side split (Logs) or stacked list then detail (Knowledge browse). */
    layout?: 'split' | 'stack';
    /**
     * `contained` — fixed-height parent owns the scroll; the split clips and the
     * list scrolls internally (default).
     * `page` — the document scrolls; no clipping ancestor so a list table can use
     * page-level sticky headers, and the detail is expected to pin itself sticky.
     */
    scroll?: 'contained' | 'page';
    splitClass?: string;
    class?: string;
    list: Snippet;
    detail: Snippet;
  };

  let {
    detailOpen = $bindable(false),
    layout = 'split',
    scroll = 'contained',
    splitClass = 'min-[1180px]:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]',
    class: className,
    list,
    detail
  }: Props = $props();
</script>

<div
  class={cn(
    'grid grid-cols-1 gap-3',
    // `page` mode must not clip: a clipping ancestor would scope the table's
    // sticky head to this box instead of the document.
    scroll === 'contained' && 'min-h-0 overflow-hidden',
    layout === 'split' && detailOpen && splitClass,
    layout === 'stack' && detailOpen && 'gap-4',
    className
  )}
>
  <div
    class={cn(
      'min-w-0',
      layout === 'split'
        ? cn('flex flex-col', scroll === 'contained' && 'min-h-0 overflow-hidden')
        : 'contents'
    )}
  >
    {@render list()}
  </div>
  {#if detailOpen}
    {@render detail()}
  {/if}
</div>
