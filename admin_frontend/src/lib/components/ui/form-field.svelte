<script lang="ts">
  /**
   * Replaces ad-hoc ``:global(.field)`` on Characters: stacks label + primitives with shared border/typography.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  let {
    label,
    class: className = '',
    children
  }: {
    label?: string;
    class?: string;
    children: Snippet;
  } = $props();
</script>

<label class={cn('admin-ui-form-field grid gap-1.5 text-left', className)}>
  {#if label?.trim()}
    <span class="font-sans text-sm font-semibold leading-snug text-muted-foreground">{label}</span>
  {/if}
  {@render children()}
</label>

<style>
  .admin-ui-form-field :global(textarea),
  .admin-ui-form-field :global(select:not([multiple])),
  .admin-ui-form-field
    :global(
      input:not([type='range']):not([type='checkbox']):not([type='radio']):not([type='file']):not([type='hidden'])
    ) {
    min-height: 2.25rem;
    width: 100%;
    border-radius: 0.375rem;
    border: 1px solid var(--input);
    background: var(--background);
    color: var(--foreground);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-title);
    font-size: 0.875rem;
    outline: none;
  }

  .admin-ui-form-field :global(select[multiple]) {
    min-height: 8rem;
    width: 100%;
    border-radius: 0.375rem;
    border: 1px solid var(--input);
    background: var(--background);
    color: var(--foreground);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-title);
    font-size: 0.875rem;
    outline: none;
  }

  .admin-ui-form-field :global(input[type='range']) {
    width: 100%;
  }
</style>
