<script lang="ts">
  /**
   * Left-side "Graph options" panel for the knowledge graph view. Holds live
   * layout controls; the parent (KnowledgeGraphPanel) owns the values and applies
   * them to the force-graph instance via $effects. Toggled by a button in the
   * graph's upper-left corner.
   */
  import { X } from '@lucide/svelte';

  let {
    linkStrength = $bindable(),
    curveAmount = $bindable(),
    onClose
  }: {
    /** d3 link-force strength: 0 = loose, 1 = rigid. */
    linkStrength: number;
    /** Max bow for fanned parallel edges: 0 = straight, 1 = very curved. */
    curveAmount: number;
    onClose: () => void;
  } = $props();
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
  </div>
</div>
