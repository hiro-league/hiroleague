<script lang="ts">
  import { Maximize2, Minimize2, RefreshCw, Scan, Shuffle, SlidersHorizontal } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  let {
    controlsSide,
    showGraphControls = false,
    optionsOpen = false,
    loading = false,
    fullscreen = false,
    onToggleOptions,
    onRedraw,
    onFit,
    onReload,
    onToggleFullscreen
  }: {
    controlsSide: 'left' | 'right';
    showGraphControls?: boolean;
    optionsOpen?: boolean;
    loading?: boolean;
    fullscreen?: boolean;
    onToggleOptions: () => void;
    onRedraw: () => void;
    onFit: () => void;
    onReload: () => void;
    onToggleFullscreen: () => void;
  } = $props();

  const ctrlBtn =
    'rounded-md border bg-background/85 p-1.5 text-muted-foreground shadow-sm backdrop-blur transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50 disabled:hover:bg-background/85';
</script>

<div
  class={cn(
    'absolute top-2 z-10 flex items-center gap-1',
    controlsSide === 'left' ? 'left-2' : 'right-2'
  )}
>
  {#if showGraphControls}
    <button
      type="button"
      onclick={onToggleOptions}
      class={cn(ctrlBtn, optionsOpen && 'text-foreground')}
      aria-label={optionsOpen ? 'Hide graph options' : 'Show graph options'}
      aria-pressed={optionsOpen}
      title="Graph options"
    >
      <SlidersHorizontal size={16} aria-hidden="true" />
    </button>
    <button
      type="button"
      onclick={onRedraw}
      class={ctrlBtn}
      aria-label="Redraw layout with current filters"
      title="Redraw — re-run the layout on the current (filtered) graph"
    >
      <Shuffle size={16} aria-hidden="true" />
    </button>
    <button
      type="button"
      onclick={onFit}
      class={ctrlBtn}
      aria-label="Fit graph to view"
      title="Fit to view"
    >
      <Scan size={16} aria-hidden="true" />
    </button>
  {/if}
  <button
    type="button"
    onclick={onReload}
    disabled={loading}
    class={ctrlBtn}
    aria-label="Reload graph from server"
    title="Reload — re-fetch the graph from the server"
  >
    <RefreshCw size={16} class={loading ? 'animate-spin' : ''} aria-hidden="true" />
  </button>
  <button
    type="button"
    onclick={onToggleFullscreen}
    class={ctrlBtn}
    aria-label={fullscreen ? 'Exit full screen (Esc)' : 'View graph full screen'}
    title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}
  >
    {#if fullscreen}
      <Minimize2 size={16} aria-hidden="true" />
    {:else}
      <Maximize2 size={16} aria-hidden="true" />
    {/if}
  </button>
</div>
