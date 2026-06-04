<script lang="ts">
  /**
   * Left-side "Graph options" panel for the knowledge graph view. Holds live
   * layout controls; the parent (KnowledgeGraphPanel) owns the values and applies
   * them to the force-graph instance via $effects. Toggled by a button in the
   * graph's upper-left corner.
   */
  import { X } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import type { SearchFocusMode } from './knowledge-graph-prefs';

  let {
    linkStrength = $bindable(),
    linkDistance = $bindable(),
    curveAmount = $bindable(),
    maxLinksPerPair = $bindable(),
    searchFocusMode = $bindable(),
    maxLinksCap,
    onReset,
    onClose
  }: {
    /** d3 link-force strength: 0 = loose, 1 = rigid. */
    linkStrength: number;
    /** d3 link-force resting length, in px. */
    linkDistance: number;
    /** Max bow for fanned parallel edges: 0 = straight, 1 = very curved. */
    curveAmount: number;
    /** Max parallel edges drawn per node pair; === maxLinksCap means "show all". */
    maxLinksPerPair: number;
    /** How a search treats non-matching nodes/edges (ring-only / dim / hide). */
    searchFocusMode: SearchFocusMode;
    /** The maxLinksPerPair value that means "show all" (slider's max). */
    maxLinksCap: number;
    /** Restore all graph options to their defaults. */
    onReset: () => void;
    onClose: () => void;
  } = $props();

  // Segmented control for the search-focus mode. Labels stay short to fit the 14rem panel.
  const FOCUS_MODES: { value: SearchFocusMode; label: string; title: string }[] = [
    { value: 'highlight', label: 'Ring', title: 'Ring matches only; leave the rest unchanged' },
    { value: 'dim', label: 'Dim', title: 'Fade non-matching nodes and edges' },
    { value: 'hide', label: 'Hide', title: 'Hide non-matching nodes and edges' }
  ];
</script>

<div class="w-56 rounded-lg border bg-background/95 p-3 shadow-md backdrop-blur">
  <div class="mb-2.5 flex items-center justify-between">
    <h3 class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Graph options</h3>
    <button
      type="button"
      onclick={onClose}
      class="rounded p-0.5 text-muted-foreground hover:bg-accent"
      aria-label="Hide graph options"
    >
      <X size={14} aria-hidden="true" />
    </button>
  </div>

  <div class="space-y-3.5">
    <label class="block">
      <div class="mb-1 flex items-center justify-between text-xs">
        <span class="font-medium">Link strength</span>
        <span class="tabular-nums text-muted-foreground">{linkStrength.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        bind:value={linkStrength}
        class="h-1.5 w-full cursor-pointer accent-primary"
        aria-label="Link strength between nodes"
      />
      <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>loose</span><span>tight</span>
      </div>
    </label>

    <label class="block">
      <div class="mb-1 flex items-center justify-between text-xs">
        <span class="font-medium">Link distance</span>
        <span class="tabular-nums text-muted-foreground">{linkDistance}</span>
      </div>
      <input
        type="range"
        min="20"
        max="300"
        step="5"
        bind:value={linkDistance}
        class="h-1.5 w-full cursor-pointer accent-primary"
        aria-label="Resting distance of edges between nodes"
      />
      <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>near</span><span>far</span>
      </div>
    </label>

    <label class="block">
      <div class="mb-1 flex items-center justify-between text-xs">
        <span class="font-medium">Edge curvature</span>
        <span class="tabular-nums text-muted-foreground">{curveAmount.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        bind:value={curveAmount}
        class="h-1.5 w-full cursor-pointer accent-primary"
        aria-label="Curvature of edges between nodes"
      />
      <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>straight</span><span>curved</span>
      </div>
    </label>

    <label class="block">
      <div class="mb-1 flex items-center justify-between text-xs">
        <span class="font-medium">Max links per pair</span>
        <span class="tabular-nums text-muted-foreground"
          >{maxLinksPerPair >= maxLinksCap ? 'All' : maxLinksPerPair}</span
        >
      </div>
      <input
        type="range"
        min="1"
        max={maxLinksCap}
        step="1"
        bind:value={maxLinksPerPair}
        class="h-1.5 w-full cursor-pointer accent-primary"
        aria-label="Maximum number of edges shown between any two nodes"
      />
      <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>1</span><span>all</span>
      </div>
    </label>

    <!-- Search focus: what a search does to NON-matching nodes/edges. -->
    <div>
      <div class="mb-1 text-xs">
        <span class="font-medium">Search focus</span>
      </div>
      <div
        class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5"
        role="group"
        aria-label="How search treats non-matching nodes and edges"
      >
        {#each FOCUS_MODES as mode (mode.value)}
          {@const active = searchFocusMode === mode.value}
          <button
            type="button"
            onclick={() => (searchFocusMode = mode.value)}
            class={cn(
              'rounded px-1.5 py-1 text-xs font-medium transition-colors',
              active
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            )}
            aria-pressed={active}
            title={mode.title}
          >
            {mode.label}
          </button>
        {/each}
      </div>
    </div>
  </div>

  <button
    type="button"
    onclick={onReset}
    class="mt-3 w-full rounded-md border px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
  >
    Reset to defaults
  </button>
</div>
