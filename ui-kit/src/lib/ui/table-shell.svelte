<script lang="ts">
  import type { Snippet } from 'svelte';
  import * as Table from '$kit/components/ui/table/index.js';
  import { cn } from '$kit/utils';
  // pinned beneath the shell's top bar, the page header and a sticky bar (all published as CSS variables)
  const TABLE = 'w-full text-left text-sm';
  const STICKY_TOP = 'calc(var(--app-top, 0px) + var(--page-header, 0px) + var(--sticky-bar, 0px))';

  type Props = {
    /** Semantic `<table>` (default) or CSS-grid row layout for wide admin tables. */
    layout?: 'table' | 'grid';
    /** Minimum inner width for horizontal scroll (grid layout). */
    minWidth?: number | string;
    /** Grid template columns when `layout="grid"`. */
    gridColumns?: string;
    /** Pin the head row beneath sticky page chrome. */
    stickyHead?: boolean;
    /** Override `--table-sticky-top` when `stickyHead` is set (eval toolbars, etc.). */
    stickyTop?: string;
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
    stickyTop,
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

  /** Pin beneath page chrome (document scroll). Requires no overflow ancestor. */
  const pageStickyHead = $derived(stickyHead && !maxBodyHeight);
  /** Pin within a max-height body scroller (nested panels). */
  const containerStickyHead = $derived(stickyHead && !!maxBodyHeight);
</script>

<div
  class={cn(
    'table-shell rounded-md border',
    density === 'default' && 'bg-card',
    // overflow-x on the shell breaks page-level sticky; only use it when the head is not page-pinned.
    density === 'default' && !pageStickyHead && 'overflow-x-auto',
    density === 'dense' && 'table-shell-dense',
    density === 'dense' && !stickyHead && 'overflow-auto',
    pageStickyHead && layout === 'table' && density === 'default' && 'table-shell-sticky-page',
    containerStickyHead && layout === 'table' && density === 'default' && 'table-shell-sticky-container',
    pageStickyHead && layout === 'table' && density === 'dense' && 'table-shell-dense-sticky-page',
    className
  )}
  style:--table-sticky-top={pageStickyHead ? (stickyTop ?? STICKY_TOP) : undefined}
  data-sticky-head={stickyHead || undefined}
  data-sticky-scope={pageStickyHead ? 'page' : containerStickyHead ? 'container' : undefined}
  data-density={density}
>
  {#if layout === 'grid'}
    <div style:min-width={minWidthStyle}>
      {#if headRow}
        <div
          class={cn(
            'table-grid-head',
            pageStickyHead && 'table-grid-head-sticky-page',
            containerStickyHead && 'table-grid-head-sticky-container'
          )}
          style:grid-template-columns={gridColumns}
        >
          {@render headRow()}
        </div>
      {/if}
      <div class={cn(maxBodyHeight && 'overflow-auto', !pageStickyHead && 'overflow-x-auto')} style:max-height={maxBodyHeight}>
        {@render body?.()}
      </div>
    </div>
  {:else}
    <div
      class={cn(maxBodyHeight && 'overflow-auto', !pageStickyHead && 'overflow-x-auto')}
      style:max-height={maxBodyHeight}
    >
      <Table.Root scroll={false} class={TABLE}>
        {@render children?.()}
      </Table.Root>
    </div>
  {/if}
</div>

<style>
  /* Page scroll: pin beneath shell bar + sticky page header + sticky toolbar.
     `--table-sticky-top` is set inline by the shell; v-bind cannot bind a
     plain JS constant, so we publish the value via a CSS variable instead. */
  .table-shell-sticky-page :global(thead th),
  .table-grid-head-sticky-page {
    position: sticky;
    top: var(--table-sticky-top, var(--app-top, 0px));
    z-index: 5;
  }

  .table-shell-sticky-page :global(thead th) {
    background: var(--muted);
    box-shadow: 0 1px 0 var(--border);
  }

  .table-grid-head-sticky-page {
    box-shadow: 0 1px 0 var(--border);
  }

  /* Nested max-height scroller: pin at top of the scroll container. */
  .table-shell-sticky-container :global(thead th),
  .table-grid-head-sticky-container {
    position: sticky;
    top: 0;
    z-index: 1;
  }

  .table-shell-sticky-container :global(thead th) {
    background: var(--muted);
  }

  .table-grid-head {
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

  /* Ledger-style tables (Graph Runs) — matches former GraphRunsTableShell. */
  .table-shell-dense :global(table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    white-space: nowrap;
    text-align: left;
  }

  .table-shell-dense :global(th),
  .table-shell-dense :global(td) {
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    text-align: left;
  }

  .table-shell-dense :global(thead th) {
    position: sticky;
    top: 0;
    background: var(--background);
    z-index: 1;
    font-weight: inherit;
    text-transform: none;
  }

  /* Dense tables pinned beneath page chrome on document scroll. */
  .table-shell-dense-sticky-page :global(thead th) {
    top: var(--table-sticky-top, var(--app-top, 0px));
    z-index: 5;
    box-shadow: 0 1px 0 var(--border);
  }
</style>
