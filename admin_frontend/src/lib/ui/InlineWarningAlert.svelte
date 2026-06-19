<script lang="ts">
  /**
   * Single canonical inline warning block (e.g. live poll degraded but page usable).
   *
   * Pairs with `InlineDestructiveAlert` for blocking config errors and
   * `InlineLoading` / `InlineEmptyState` for other blessed inline feedback.
   */
  import { cn } from '$lib/utils';

  type Props = {
    message: string;
    title?: string;
    class?: string;
  };

  let { message, title, class: className }: Props = $props();
</script>

<div
  class={cn(
    'rounded-md border border-amber-500/30 bg-amber-500/10 p-3 font-sans text-sm text-amber-700 dark:text-amber-300',
    className
  )}
>
  {#if title}
    <strong class="font-semibold">{title}</strong>
    <span class="block">{message}</span>
  {:else}
    <span>{message}</span>
  {/if}
</div>
