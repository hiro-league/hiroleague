<script lang="ts" generics="TCol extends import('$lib/features/eval/state/eval-answer-sort.svelte').EvalAnswerSortColumn">
  import { ChevronDown, ChevronUp, ChevronsUpDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import type { EvalAnswerSortController } from '$lib/features/eval/state/eval-answer-sort.svelte';

  type Props = {
    column: TCol;
    sort: EvalAnswerSortController;
    class?: string;
    sortable?: boolean;
    title?: string;
    children: import('svelte').Snippet;
  };

  let { column, sort, class: className, sortable = true, title = '', children }: Props = $props();

  const active = $derived(sort.sortKey === column);
</script>

<th
  class={cn('px-3 py-2 text-left', className)}
  aria-sort={sortable ? sort.ariaSort(column) : undefined}
>
  {#if sortable}
    <button
      type="button"
      class="inline-flex items-center gap-1 font-inherit uppercase tracking-wide hover:text-foreground"
      onclick={() => sort.toggle(column)}
      {title}
    >
      {@render children()}
      {#if active}
        {#if sort.sortDir === 'asc'}
          <ChevronUp size={12} aria-hidden="true" />
        {:else}
          <ChevronDown size={12} aria-hidden="true" />
        {/if}
      {:else}
        <ChevronsUpDown size={12} class="opacity-30" aria-hidden="true" />
      {/if}
    </button>
  {:else}
    {@render children()}
  {/if}
</th>
