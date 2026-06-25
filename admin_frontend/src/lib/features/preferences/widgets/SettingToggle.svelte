<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';

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
  };

  let {
    label,
    checked = $bindable(false),
    disabled = false,
    class: className = '',
    hint,
    details,
    onchange
  }: Props = $props();
</script>

<label
  class={cn(
    'flex gap-3 rounded-md border border-border/50 bg-card/45 px-3',
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
