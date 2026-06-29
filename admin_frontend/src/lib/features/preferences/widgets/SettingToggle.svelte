<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import ResetDot from '$lib/components/ui/reset-dot.svelte';

  type Props = {
    label: string;
    checked?: boolean;
    disabled?: boolean;
    class?: string;
    // Plain-text help shown as a hover tooltip on a help icon next to the label.
    hint?: string;
    // Rich help rendered below the label (markup the tooltip can't carry).
    details?: Snippet;
    onchange?: () => void;
    // When true (and `onReset` given), render a "reset to default" dot after the label/help icon.
    showReset?: boolean;
    onReset?: () => void;
    // Optional dotted preference path; tags the row so Settings search can scroll to + highlight it.
    anchor?: string;
  };

  let {
    label,
    checked = $bindable(false),
    disabled = false,
    class: className = '',
    hint,
    details,
    onchange,
    showReset = false,
    onReset,
    anchor
  }: Props = $props();
</script>

<label
  data-pref-path={anchor}
  class={cn(
    'group flex gap-3 rounded-md border border-border/50 bg-card/45 px-3',
    details ? 'items-start py-2.5' : 'min-h-10 items-center',
    className
  )}
>
  <input
    type="checkbox"
    class={details ? 'mt-0.5' : undefined}
    bind:checked
    {disabled}
    onchange={() => onchange?.()}
  />
  {#snippet labelRow()}
    <span class="inline-flex items-center gap-1.5 font-sans text-sm font-medium">
      {label}
      {#if hint?.trim()}
        <FieldHelp text={hint} />
      {/if}
      {#if showReset && onReset}
        <!-- Hidden until the toggle row is hovered/focused (see FormField) to avoid icon clutter. -->
        <ResetDot
          {onReset}
          class="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
        />
      {/if}
    </span>
  {/snippet}
  {#if details}
    <span class="grid gap-0.5">
      {@render labelRow()}
      <span class="font-sans text-xs text-muted-foreground">
        {@render details()}
      </span>
    </span>
  {:else}
    {@render labelRow()}
  {/if}
</label>
