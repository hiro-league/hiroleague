<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    detailOpen?: boolean;
    /** Side-by-side split (Logs) or stacked list then detail (Knowledge browse). */
    layout?: 'split' | 'stack';
    splitClass?: string;
    class?: string;
    list: Snippet;
    detail: Snippet;
  };

  let {
    detailOpen = $bindable(false),
    layout = 'split',
    splitClass = 'min-[1180px]:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]',
    class: className,
    list,
    detail
  }: Props = $props();
</script>

<div
  class={cn(
    'grid min-h-0 grid-cols-1 gap-3 overflow-hidden',
    layout === 'split' && detailOpen && splitClass,
    layout === 'stack' && detailOpen && 'gap-4',
    className
  )}
>
  <div class={cn('min-h-0 min-w-0', layout === 'split' ? 'flex flex-col overflow-hidden' : 'contents')}>
    {@render list()}
  </div>
  {#if detailOpen}
    {@render detail()}
  {/if}
</div>
