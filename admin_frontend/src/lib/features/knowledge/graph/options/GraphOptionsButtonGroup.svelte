<script lang="ts">
  import { cn } from '$lib/utils';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    title,
    dirty = false,
    onReset,
    modes,
    value,
    onChange,
    ariaLabel,
    cols = 3
  }: {
    title: string;
    dirty?: boolean;
    onReset: () => void;
    modes: { value: string; label: string; title: string }[];
    value: string;
    onChange: (v: string) => void;
    ariaLabel: string;
    cols?: 2 | 3;
  } = $props();
</script>

<div>
  <div class="mb-1 flex items-center text-xs">
    <span class="flex items-center font-medium">
      {title}
      <GraphOptionsResetDot dirty={dirty} onReset={onReset} />
    </span>
  </div>
  <div
    class={cn('grid gap-0.5 rounded-md border bg-muted/40 p-0.5', cols === 3 ? 'grid-cols-3' : 'grid-cols-2')}
    role="group"
    aria-label={ariaLabel}
  >
    {#each modes as mode (mode.value)}
      {@const active = value === mode.value}
      <button
        type="button"
        onclick={() => onChange(mode.value)}
        class={cn(
          'rounded px-1.5 py-1 text-xs font-medium transition-colors',
          active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
        )}
        aria-pressed={active}
        title={mode.title}
      >
        {mode.label}
      </button>
    {/each}
  </div>
</div>
