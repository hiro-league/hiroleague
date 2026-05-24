<script lang="ts">
  /**
   * Single canonical inline destructive-error block.
   *
   * Replaces the `border-destructive/30 bg-destructive/10` blocks copy-pasted
   * across 15+ pages. After Phase 2 this is the only blessed shape for inline
   * destructive feedback (toasts/dialogs remain for transient / blocking
   * cases).
   */
  import { cn } from '$lib/utils';

  type Props = {
    message: string;
    title?: string;
    class?: string;
  };

  let { message, title, class: className }: Props = $props();
</script>

<div class={cn('rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive', className)}>
  {#if title}
    <strong class="font-sans">{title}</strong>
    <span class="block text-sm">{message}</span>
  {:else}
    <span class="font-sans text-sm">{message}</span>
  {/if}
</div>
