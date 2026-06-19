<script lang="ts">
  import type { FlowSeg } from './retrieval-trace-derive';

  // The retrieval lane's "funnel" strip — the at-a-glance mental model of a lane: parallel legs →
  // rank → temporal lens. Each pill jumps to (and expands) its stage. Extracted from the dialog;
  // owns the `.flow*` styles, which were used nowhere else.
  let {
    flow,
    title,
    onJump
  }: { flow: FlowSeg[]; title: string; onJump: (idx: number) => void } = $props();
</script>

<nav class="flow" aria-label={`${title} stages`}>
  {#each flow as seg, fi (fi)}
    {#if fi > 0}<span class="flow__arrow">→</span>{/if}
    <button
      type="button"
      class="flow__seg flow__seg--{seg.emphasis}"
      title={`Jump to ${seg.label}`}
      onclick={() => onJump(seg.idx)}
    >
      <span class="flow__count">{seg.count}</span>
      <span class="flow__label">{seg.label}</span>
    </button>
  {/each}
</nav>

<style>
  /* Funnel strip — the at-a-glance mental model of the lane. Sticky so the clickable stage
     pills stay reachable while scrolling the tables; opaque bg + z-index so rows pass under it. */
  .flow {
    position: sticky;
    top: 0;
    z-index: 2;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px 0;
    background: var(--popover);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 16%, transparent);
  }

  .flow__arrow {
    color: var(--muted-foreground);
    font-size: 12px;
  }

  .flow__seg {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 25%, transparent);
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
    font-size: 11px;
    cursor: pointer;
    transition:
      transform 0.08s ease,
      box-shadow 0.08s ease,
      background 0.08s ease;
  }

  .flow__seg:hover {
    background: color-mix(in srgb, var(--muted-foreground) 16%, transparent);
    transform: translateY(-1px);
  }

  .flow__seg:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 1px;
  }

  .flow__seg--rank {
    border-color: color-mix(in srgb, var(--primary) 45%, transparent);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
  }

  .flow__seg--final {
    border-color: color-mix(in srgb, var(--primary) 70%, transparent);
    background: color-mix(in srgb, var(--primary) 22%, transparent);
    font-weight: 600;
  }

  .flow__count {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--foreground);
  }

  .flow__label {
    color: var(--muted-foreground);
  }
</style>
