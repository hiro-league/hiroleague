<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import {
    ADMIN_TABLE,
    ADMIN_TABLE_GRID_HEAD,
    ADMIN_TABLE_STICKY_TOP
  } from '$lib/styling/admin-tokens';

  type Props = {
    /** Semantic `<table>` (default) or CSS-grid row layout for wide admin tables. */
    layout?: 'table' | 'grid';
    /** Minimum inner width for horizontal scroll (grid layout). */
    minWidth?: number | string;
    /** Grid template columns when `layout="grid"`. */
    gridColumns?: string;
    /** Pin the head row beneath sticky page chrome. */
    stickyHead?: boolean;
    /**
     * `default` — catalog/server tables (14px, muted uppercase head).
     * `dense` — ledger-style lists (12px, plain head, cell bottom borders).
     */
    density?: 'default' | 'dense';
    /** Max height + vertical scroll for the body region. */
    maxBodyHeight?: string;
    class?: string;
    /** Table mode: `<thead>` / `<tbody>` children. Grid mode: ignored when headRow/body set. */
    children?: Snippet;
    /** Grid mode: sticky header cells. */
    headRow?: Snippet;
    /** Grid mode: body rows. */
    body?: Snippet;
  };

  let {
    layout = 'table',
    minWidth,
    gridColumns,
    stickyHead = false,
    density = 'default',
    maxBodyHeight,
    class: className,
    children,
    headRow,
    body
  }: Props = $props();

  const minWidthStyle = $derived(
    minWidth === undefined ? undefined : typeof minWidth === 'number' ? `${minWidth}px` : minWidth
  );
</script>

<div
  class={cn(
    'rounded-md border',
    density === 'default' && 'overflow-x-auto bg-card',
    density === 'dense' && 'admin-table-shell-dense overflow-auto',
    stickyHead && layout === 'table' && density === 'default' && 'admin-table-shell-sticky',
    className
  )}
  data-sticky-head={stickyHead || undefined}
  data-density={density}
>
  {#if layout === 'grid'}
    <div style:min-width={minWidthStyle}>
      {#if headRow}
        <div
          class={cn('admin-table-grid-head', stickyHead && 'admin-table-grid-head-sticky')}
          style:grid-template-columns={gridColumns}
        >
          {@render headRow()}
        </div>
      {/if}
      <div class={cn(maxBodyHeight && 'overflow-auto')} style:max-height={maxBodyHeight}>
        {@render body?.()}
      </div>
    </div>
  {:else}
    <div class={cn(maxBodyHeight && 'overflow-auto')} style:max-height={maxBodyHeight}>
      <table class={ADMIN_TABLE}>
        {@render children?.()}
      </table>
    </div>
  {/if}
</div>

<style>
  .admin-table-shell-sticky :global(thead) {
    position: sticky;
    top: v-bind(ADMIN_TABLE_STICKY_TOP);
    z-index: 1;
    background: var(--muted);
  }

  .admin-table-grid-head {
    display: grid;
    gap: 0.75rem;
    background: var(--muted);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-title);
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }

  .admin-table-grid-head-sticky {
    position: sticky;
    top: v-bind(ADMIN_TABLE_STICKY_TOP);
    z-index: 1;
  }

  /* Ledger-style tables (Graph Runs) — matches former GraphRunsTableShell. */
  .admin-table-shell-dense :global(table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    white-space: nowrap;
    text-align: left;
  }

  .admin-table-shell-dense :global(th),
  .admin-table-shell-dense :global(td) {
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    text-align: left;
  }

  .admin-table-shell-dense :global(thead th) {
    position: sticky;
    top: 0;
    background: var(--background);
    z-index: 1;
    font-weight: inherit;
    text-transform: none;
  }
</style>
