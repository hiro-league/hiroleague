<script lang="ts">
  import { X } from '@lucide/svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_SELECT, ADMIN_SELECT_SM, FILTER_CLEAR_ICON_BTN } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Option = { value: string; label: string };

  type Props = {
    label?: string;
    value?: string;
    options?: readonly Option[];
    placeholder?: string;
    class?: string;
    selectClass?: string;
    onValueChange?: (value: string) => void;
    clearable?: boolean;
    onClear?: () => void;
    /** Toolbar-style row (logs filters) instead of a FormField block. */
    layout?: 'field' | 'inline';
    title?: string;
  };

  let {
    label,
    value = $bindable(''),
    options = [],
    placeholder,
    class: className,
    selectClass,
    onValueChange,
    clearable = false,
    onClear,
    layout = 'field',
    title
  }: Props = $props();

  function clearValue() {
    if (onClear) {
      onClear();
      return;
    }
    value = '';
    onValueChange?.('');
  }
</script>

{#if layout === 'inline'}
  {#if label}
    <span class="font-sans text-sm font-semibold text-muted-foreground">{label}</span>
  {/if}
  <div class={cn('flex items-center gap-0.5', className)}>
    <select
      class={cn(ADMIN_SELECT_SM, selectClass)}
      bind:value
      {title}
      onchange={() => onValueChange?.(value)}
    >
      {#if placeholder}
        <option value="">{placeholder}</option>
      {/if}
      {#each options as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
    <div class="inline-flex size-8 shrink-0 items-center justify-center">
      {#if clearable && value.trim()}
        <Button
          variant="ghost"
          size="icon"
          class={FILTER_CLEAR_ICON_BTN}
          onclick={clearValue}
          title="Clear filter"
          aria-label="Clear filter"
        >
          <X size={15} strokeWidth={2} />
        </Button>
      {/if}
    </div>
  </div>
{:else}
  <FormField {label} class={cn('min-w-[10rem]', className)}>
    <div class="flex items-center gap-0.5">
      <select
        class={cn(ADMIN_SELECT, 'w-full', selectClass)}
        bind:value
        {title}
        onchange={() => onValueChange?.(value)}
      >
        {#if placeholder}
          <option value="">{placeholder}</option>
        {/if}
        {#each options as option (option.value)}
          <option value={option.value}>{option.label}</option>
        {/each}
      </select>
      {#if clearable && value.trim()}
        <Button
          variant="ghost"
          size="icon"
          class={FILTER_CLEAR_ICON_BTN}
          onclick={clearValue}
          title="Clear filter"
          aria-label="Clear filter"
        >
          <X size={15} strokeWidth={2} />
        </Button>
      {/if}
    </div>
  </FormField>
{/if}
