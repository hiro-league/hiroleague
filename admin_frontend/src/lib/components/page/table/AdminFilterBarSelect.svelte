<script lang="ts">
  import { X } from '@lucide/svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import { FILTER_CLEAR_ICON_BTN } from '$lib/styling/admin-tokens';
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

  /** The placeholder choice ("All …") stands for ''; PickSelect cannot pick an empty value. */
  const ANY = '__any';
  const choices = $derived(placeholder ? [{ value: ANY, label: placeholder }, ...options] : options);

  function pick(v: string) {
    value = v === ANY ? '' : v;
    onValueChange?.(value);
  }

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
    <span class="inline-flex min-w-0" {title}>
      <PickSelect
        value={value || (placeholder ? ANY : '')}
        options={choices}
        onchange={pick}
        {placeholder}
        label={label ?? placeholder}
        class={cn('h-8 min-w-0 text-sm', selectClass)}
      />
    </span>
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
      <span class="flex min-w-0 flex-1" {title}>
        <PickSelect
          value={value || (placeholder ? ANY : '')}
          options={choices}
          onchange={pick}
          {placeholder}
          label={label ?? placeholder}
          class={cn('h-8 w-full text-sm', selectClass)}
        />
      </span>
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
