<script lang="ts">
  /**
   * Layout owner for preference fields. Replaces per-field `max-w-*` self-capping and the ad-hoc
   * `md:grid-cols-*` wrappers that used to live in each card: a field is now a grid cell that fills
   * its column, and the COLUMN COUNT is decided here (the slot), not by the control itself.
   *
   * Default is a responsive 2-column grid (single column below `md` so it collapses on narrow
   * viewports). `cols={3}` is the explicit exception for dense numeric rows. `items-start` keeps
   * uneven-height neighbours top-aligned (a field with a long label/tooltip next to a short one).
   *
   * Model pickers can sit in grid cells too (see the Default models card), so the 2-column layout
   * holds for them like everything else. Genuinely full-bleed controls (prompt editors, the
   * extraction textarea) still live OUTSIDE this grid as full-width siblings; add a
   * `md:col-span-full` opt-in on a field if you need an in-grid full-span row.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    /** Columns at `md` and up. 2 is the default; 3 is the dense-numeric exception. */
    cols?: 2 | 3;
    class?: string;
    children: Snippet;
  };

  let { cols = 2, class: className = '', children }: Props = $props();

  // Literal class strings so Tailwind's JIT picks them up (no dynamic `md:grid-cols-${cols}`).
  const colsClass = $derived(cols === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2');
</script>

<div class={cn('grid grid-cols-1 items-start gap-x-8 gap-y-3', colsClass, className)}>
  {@render children()}
</div>
