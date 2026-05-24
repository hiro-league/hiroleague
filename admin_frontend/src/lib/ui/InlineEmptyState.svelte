<script lang="ts">
  /**
   * Single canonical inline "empty state" placeholder.
   *
   * For lists/tables/sections that have loaded with zero rows. Supports a
   * leading icon (snippet), a message, and an optional secondary action area.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    message: string;
    /** Optional small caption shown beneath the message. */
    hint?: string;
    /** Optional extra classes appended to the wrapper. */
    class?: string;
    icon?: Snippet;
    actions?: Snippet;
  };

  let { message, hint, class: className, icon, actions }: Props = $props();
</script>

<div
  class={cn(
    'flex flex-col items-center gap-2 rounded-md border border-dashed border-border bg-background/40 px-4 py-8 text-center',
    className
  )}
>
  {#if icon}
    <div class="text-muted-foreground">
      {@render icon()}
    </div>
  {/if}
  <p class="font-sans text-sm text-muted-foreground">{message}</p>
  {#if hint}
    <p class="font-sans text-xs text-muted-foreground/80">{hint}</p>
  {/if}
  {#if actions}
    <div class="mt-2 flex flex-wrap items-center justify-center gap-2">
      {@render actions()}
    </div>
  {/if}
</div>
