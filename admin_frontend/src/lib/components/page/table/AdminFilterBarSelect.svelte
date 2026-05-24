<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Option = { value: string; label: string };

  type Props = {
    label: string;
    value?: string;
    options: readonly Option[];
    placeholder?: string;
    class?: string;
    selectClass?: string;
    onValueChange?: (value: string) => void;
  };

  let {
    label,
    value = $bindable(''),
    options,
    placeholder,
    class: className,
    selectClass,
    onValueChange
  }: Props = $props();
</script>

<FormField {label} class={cn('min-w-[10rem]', className)}>
  <select
    class={cn(ADMIN_SELECT, 'w-full', selectClass)}
    bind:value
    onchange={() => onValueChange?.(value)}
  >
    {#if placeholder}
      <option value="">{placeholder}</option>
    {/if}
    {#each options as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
</FormField>
