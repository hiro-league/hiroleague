<script lang="ts">
  /**
   * Replaces ad-hoc ``:global(.field)`` on Characters: stacks label + primitives with shared border/typography.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';

  let {
    label,
    hint,
    hintTooltip = false,
    class: className = '',
    children
  }: {
    label?: string;
    // Optional help text rendered below the control (reused across settings forms).
    hint?: string;
    // When true, render `hint` as a help icon + tooltip next to the label instead of inline below.
    hintTooltip?: boolean;
    class?: string;
    children: Snippet;
  } = $props();
</script>

<label class={cn('admin-ui-form-field grid gap-1.5 text-left', className)}>
  {#if label?.trim()}
    <span
      class={cn(
        'font-sans text-sm font-semibold leading-snug text-muted-foreground',
        hint?.trim() && hintTooltip && 'inline-flex items-center gap-1.5'
      )}
    >
      {label}
      {#if hint?.trim() && hintTooltip}
        <FieldHelp text={hint} />
      {/if}
    </span>
  {/if}
  {@render children()}
  {#if hint?.trim() && !hintTooltip}
    <span class="font-sans text-xs leading-snug text-muted-foreground">{hint}</span>
  {/if}
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
