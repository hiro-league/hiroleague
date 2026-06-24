<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  export type AdminIconToggleOption = {
    value: string;
    label: string;
    Icon?: Component<{ size?: number; strokeWidth?: number; class?: string }>;
    dotClass?: string;
  };

  let {
    label,
    labelId,
    layout = 'stacked',
    appearance = 'filter',
    activeStyle = 'solid',
    options,
    isSelected,
    onToggle,
    optionContent,
    groupClass = '',
    containerClass = ''
  }: {
    label?: string;
    labelId?: string;
    layout?: 'stacked' | 'inline';
    appearance?: 'filter' | 'toolbar';
    activeStyle?: 'solid' | 'muted';
    options: AdminIconToggleOption[];
    isSelected: (value: string) => boolean;
    onToggle: (value: string) => void;
    /** Override inner button content (e.g. LogLevelIcon with accent classes). */
    optionContent?: Snippet<[AdminIconToggleOption, boolean]>;
    groupClass?: string;
    containerClass?: string;
  } = $props();
  function filterButtonClass(on: boolean): string {
    return cn(
      'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent transition-colors',
      activeStyle === 'solid' &&
        (on
          ? 'bg-primary text-primary-foreground shadow-sm border-primary/20'
          : 'text-muted-foreground opacity-55 hover:opacity-100'),
      activeStyle === 'muted' &&
        (on ? 'bg-primary/10 shadow-sm border-primary/20' : 'opacity-55 hover:opacity-100')
    );
  }
</script>

{#if layout === 'stacked'}
  <div class={cn('grid gap-1 font-sans text-xs font-semibold text-muted-foreground', groupClass)}>
    {#if label}
      <span id={labelId}>{label}</span>
    {/if}
    <div
      class={cn(
        'flex h-9 items-center justify-center rounded-md border bg-background',
        appearance === 'filter' && !containerClass && 'gap-0.5 px-1',
        containerClass
      )}
      role="group"
      aria-labelledby={labelId}
    >
      {#each options as option (option.value)}
        {@const on = isSelected(option.value)}
        <button
          type="button"
          class={filterButtonClass(on)}
          title={option.label}
          aria-label={option.label}
          aria-pressed={on}
          onclick={() => onToggle(option.value)}
        >
          {#if optionContent}
            {@render optionContent(option, on)}
          {:else if option.dotClass}
            <span class={cn('size-2 rounded-full', option.dotClass)} aria-hidden="true"></span>
          {:else if option.Icon}
            <span aria-hidden="true">
              <option.Icon size={16} strokeWidth={on ? 2.25 : 2} />
            </span>          {/if}
        </button>
      {/each}
    </div>
  </div>
{:else}
  <div class={cn('flex items-center gap-1', groupClass)} role="group" aria-label={label}>
    {#if label}
      <span class="font-sans text-sm font-semibold text-muted-foreground">{label}</span>
    {/if}
    {#each options as option (option.value)}
      {@const on = isSelected(option.value)}
      <Button
        size="icon"
        variant={on ? 'secondary' : 'ghost'}
        class="size-7 shrink-0 shadow-none"
        title={option.label}
        aria-label={option.label}
        aria-pressed={on}
        onclick={() => onToggle(option.value)}
      >
        {#if optionContent}
          {@render optionContent(option, on)}
        {:else if option.Icon}
          <span aria-hidden="true">
            <option.Icon size={14} />
          </span>        {/if}
      </Button>
    {/each}
  </div>
{/if}
