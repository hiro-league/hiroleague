<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    label?: string;
    value?: string;
    placeholder?: string;
    class?: string;
    inputClass?: string;
    onValueChange?: (value: string) => void;
  };

  let {
    label,
    value = $bindable(''),
    placeholder = '',
    class: className,
    inputClass,
    onValueChange
  }: Props = $props();
</script>

<FormField {label} class={cn('min-w-[12rem]', className)}>
  <input
    type="search"
    class={cn(ADMIN_INPUT, 'w-full', inputClass)}
    {placeholder}
    bind:value
    oninput={() => onValueChange?.(value)}
  />
</FormField>
