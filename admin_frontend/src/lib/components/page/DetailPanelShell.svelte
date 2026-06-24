<script lang="ts">
  import type { Snippet } from 'svelte';
  import { X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  let {
    ariaLabel,
    id,
    class: className,
    style,
    title,
    headerActions,
    footer,
    showFooter = true,
    closeLabel = 'Close',
    onClose,
    children,
    showCloseButton = true,
    bodyClass = ''
  }: {
    ariaLabel: string;
    id?: string;
    class?: string;
    style?: string;
    /** Plain string or snippet for rich title rows (graph-run step header, log details, …). */
    title: string | Snippet;
    /** Actions before the close button (copy, level badge, flip-side, …). */
    headerActions?: Snippet;
    /** Optional pinned footer below the scroll body (log timestamp bar). */
    footer?: Snippet;
    /** When false, skip the pinned-footer layout even if `footer` is passed. */
    showFooter?: boolean;
    closeLabel?: string;
    onClose: () => void;
    children?: Snippet;
    showCloseButton?: boolean;
    bodyClass?: string;
  } = $props();

  const hasFooter = $derived(Boolean(footer) && showFooter);
</script>

<aside
  {id}
  class={cn('flex min-h-0 flex-col overflow-hidden rounded-md border bg-card', className)}
  {style}
  aria-label={ariaLabel}
>
  <div class="flex min-w-0 items-center justify-between gap-3 border-b px-3 py-2.5">
    {#if typeof title === 'string'}
      <h3
        class="min-w-0 flex-1 truncate font-sans text-sm font-semibold leading-snug text-foreground"
      >
        {title}
      </h3>
    {:else}
      <div class="min-w-0 flex-1">
        {@render title()}
      </div>
    {/if}
    <div class="flex shrink-0 items-center gap-2">
      {#if headerActions}
        {@render headerActions()}
      {/if}
      {#if showCloseButton}
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0"
          aria-label={closeLabel}
          onclick={onClose}
        >
          <X size={15} />
        </Button>
      {/if}
    </div>
  </div>

  {#if hasFooter}
    <div class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden font-sans">
      <div class={cn('min-h-0 flex-1 overflow-auto p-3', bodyClass)}>
        {#if children}
          {@render children()}
        {/if}
      </div>
      {@render footer!()}
    </div>
  {:else}
    <div class={cn('min-h-0 flex-1 overflow-auto p-3 font-sans', bodyClass)}>
      {#if children}
        {@render children()}
      {/if}
    </div>
  {/if}
</aside>
