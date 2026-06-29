<script lang="ts">
  /**
   * Replaces ad-hoc ``:global(.field)`` on Characters: stacks label + primitives with shared border/typography.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import ResetDot from '$lib/components/ui/reset-dot.svelte';

  let {
    label,
    hint,
    hintTooltip = false,
    showReset = false,
    onReset,
    anchor,
    class: className = '',
    children
  }: {
    label?: string;
    // Optional help text rendered below the control (reused across settings forms).
    hint?: string;
    // When true, render `hint` as a help icon + tooltip next to the label instead of inline below.
    hintTooltip?: boolean;
    // When true (and `onReset` given), render a "reset to default" dot after the label/help icon.
    showReset?: boolean;
    onReset?: () => void;
    // Optional dotted preference path; tags the field so Settings search can scroll to + highlight it.
    anchor?: string;
    class?: string;
    children: Snippet;
  } = $props();
</script>

<label data-pref-path={anchor} class={cn('admin-ui-form-field group grid gap-1.5 text-left', className)}>
  {#if label?.trim()}
    <span
      class={cn(
        'font-sans text-sm font-semibold leading-snug text-muted-foreground',
        ((hint?.trim() && hintTooltip) || (showReset && onReset)) && 'inline-flex items-center gap-1.5'
      )}
    >
      {label}
      {#if hint?.trim() && hintTooltip}
        <FieldHelp text={hint} />
      {/if}
      {#if showReset && onReset}
        <!-- Hidden until the field (or its title) is hovered/focused, so non-default fields don't
             clutter the page with always-on reset icons. -->
        <ResetDot
          {onReset}
          class="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
        />
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
