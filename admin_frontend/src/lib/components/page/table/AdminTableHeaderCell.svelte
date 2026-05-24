<script lang="ts" generics="TCol extends string">
  import { ArrowDown, ArrowUp } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import type { TableSortController } from './use-table-sort.svelte';

  type Props = {
    column: TCol;
    sort: TableSortController<TCol>;
    class?: string;
    sortable?: boolean;
    children: import('svelte').Snippet;
  };

  let { column, sort, class: className, sortable = true, children }: Props = $props();
</script>

<th class={cn('px-3 py-2 text-left', className)} aria-sort={sortable ? sort.ariaSort(column) : undefined}>
  {#if sortable}
    <button
      type="button"
      class="inline-flex items-center gap-1 font-inherit uppercase hover:text-foreground"
      onclick={() => sort.toggle(column)}
    >
      {@render children()}
      {#if sort.sortBy === column}
        {#if sort.direction === 'asc'}
          <ArrowUp size={12} aria-hidden="true" />
        {:else}
          <ArrowDown size={12} aria-hidden="true" />
        {/if}
      {/if}
    </button>
  {:else}
    {@render children()}
  {/if}
</th>
