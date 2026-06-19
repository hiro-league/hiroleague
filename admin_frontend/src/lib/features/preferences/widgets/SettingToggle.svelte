<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    label: string;
    checked?: boolean;
    disabled?: boolean;
    class?: string;
    details?: Snippet;
    onchange?: () => void;
  };

  let {
    label,
    checked = $bindable(false),
    disabled = false,
    class: className = '',
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
  {#if details}
    <span class="grid gap-0.5">
      <span class="font-sans text-sm font-medium">{label}</span>
      <span class="font-sans text-xs text-muted-foreground">
        {@render details()}
      </span>
    </span>
  {:else}
    <span class="font-sans text-sm font-medium">{label}</span>
  {/if}
</label>
