<script lang="ts">
  import { X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SELECT_SM } from '$lib/styling/admin-tokens';
  import { FILTER_CLEAR_ICON_BTN } from './logs-classes';

  type Props = {
    value: string;
    label?: string;
    selectClass?: string;
    title?: string;
    titleClear?: string;
    ariaLabelClear?: string;
    onClear: () => void;
    onChange?: () => void;
    options: import('svelte').Snippet;
  };

  let {
    value = $bindable(''),
    label,
    selectClass = '',
    title,
    titleClear = 'Clear filter',
    ariaLabelClear = 'Clear filter',
    onClear,
    onChange,
    options
  }: Props = $props();
</script>

{#if label}
  <span class="font-sans text-sm font-semibold text-muted-foreground">{label}</span>
{/if}
<div class="flex items-center gap-0.5">
  <select
    class={cn(ADMIN_SELECT_SM, selectClass)}
    bind:value
    {title}
    onchange={() => onChange?.()}
  >
    {@render options()}
  </select>
  <div class="inline-flex size-8 shrink-0 items-center justify-center">
    {#if value.trim()}
      <Button
        variant="ghost"
        size="icon"
        class={FILTER_CLEAR_ICON_BTN}
        onclick={onClear}
        title={titleClear}
        aria-label={ariaLabelClear}
      >
        <X size={15} strokeWidth={2} />
      </Button>
    {/if}
  </div>
</div>
