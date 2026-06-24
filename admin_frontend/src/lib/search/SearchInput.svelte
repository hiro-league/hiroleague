<script lang="ts">
  import { LoaderCircle, Search, X } from '@lucide/svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_INPUT, ADMIN_SEARCH_FIELD } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    label?: string;
    value?: string;
    placeholder?: string;
    class?: string;
    inputClass?: string;
    onValueChange?: (value: string) => void;
    count?: number;
    busy?: boolean;
    size?: 'sm' | 'md';
    variant?: 'field' | 'inline' | 'compact';
    /** Passed to the underlying input when no visible label is rendered. */
    'aria-label'?: string;
  };

  let {
    label,
    value = $bindable(''),
    placeholder = '',
    class: className,
    inputClass,
    onValueChange,
    count,
    busy = false,
    size = 'md',
    variant,
    'aria-label': ariaLabel
  }: Props = $props();

  const layout = $derived(variant ?? (label ? 'field' : 'inline'));
  const showTrailing = $derived(
    value.trim().length > 0 || count !== undefined || busy
  );
  const compactTrailing = $derived(layout === 'compact' && value.trim().length > 0);

  function emitChange(next: string) {
    value = next;
    onValueChange?.(next);
  }

  function onInput(event: Event) {
    emitChange((event.currentTarget as HTMLInputElement).value);
  }

  function clearValue() {
    emitChange('');
  }

  const inputSizeClass = $derived(
    size === 'sm' ? 'h-8 text-xs' : layout === 'compact' ? 'h-8 text-xs' : ''
  );
</script>

{#if layout === 'inline'}
  <label class={cn(ADMIN_SEARCH_FIELD, className)}>
    <Search size={15} class="shrink-0 text-muted-foreground" aria-hidden="true" />
    <input
      type="search"
      class={cn(
        'min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground',
        inputClass
      )}
      {placeholder}
      aria-label={ariaLabel ?? label ?? placeholder ?? 'Search'}
      {value}
      oninput={onInput}
    />
    {#if value}
      <button
        class="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
        type="button"
        aria-label="Clear search"
        onclick={clearValue}
      >
        <X size={14} aria-hidden="true" />
      </button>
    {/if}
  </label>
{:else if layout === 'compact'}
  <div class={cn('relative', className)}>
    <Search
      size={14}
      class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
      aria-hidden="true"
    />
    <input
      type="search"
      class={cn(
        'h-8 w-44 rounded-md border bg-background pl-7 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background sm:w-52 [&::-webkit-search-cancel-button]:hidden',
        compactTrailing ? 'pr-16' : 'pr-2',
        inputClass
      )}
      {placeholder}
      aria-label={ariaLabel ?? label ?? placeholder ?? 'Search'}
      {value}
      oninput={onInput}
    />
    {#if compactTrailing}
      <div class="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
        {#if count !== undefined || busy}
          <span
            class="tabular-nums text-[10px] font-medium {(count ?? 0) > 0
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-muted-foreground'}"
            title={`${count ?? 0} match${count === 1 ? '' : 'es'}${busy ? ' (searching…)' : ''}`}
          >
            {#if busy}
              <LoaderCircle size={12} class="motion-safe:animate-spin" aria-hidden="true" />
            {:else}
              {count ?? 0}
            {/if}
          </span>
        {/if}
        <button
          type="button"
          onclick={clearValue}
          class="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Clear search"
          title="Clear search"
        >
          <X size={13} aria-hidden="true" />
        </button>
      </div>
    {/if}
  </div>
{:else}
  <FormField {label} class={cn('min-w-[12rem]', className)}>
    <div class="relative">
      <Search
        size={14}
        class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <input
        type="search"
        class={cn(
          ADMIN_INPUT,
          'w-full pl-9',
          showTrailing ? 'pr-8' : '',
          inputSizeClass,
          inputClass
        )}
        {placeholder}
        aria-label={ariaLabel ?? label ?? placeholder ?? 'Search'}
        {value}
        oninput={onInput}
      />
      {#if value}
        <button
          type="button"
          class="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          aria-label="Clear search"
          onclick={clearValue}
        >
          <X size={14} aria-hidden="true" />
        </button>
      {/if}
    </div>
  </FormField>
{/if}
