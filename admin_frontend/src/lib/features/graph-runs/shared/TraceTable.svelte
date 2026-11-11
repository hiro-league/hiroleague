<script lang="ts">
  import type { Snippet } from 'svelte';
  import * as Table from '$kit/components/ui/table/index.js';

  // Shared dense-table shell for the trace dialogs — owns the `.trace-table*` styling that was
  // duplicated ~verbatim in both. Callers pass their own `<thead>`/`<tbody>` (columns diverge per
  // lane/stage), so the cell rules use `:global()` — but anchored under this component's scoped
  // `.trace-table-wrap`, so they never leak app-wide.
  //   `out` → the structured-output variant (ingest stage tables: wrapping `.cell` / `.kv-key`).
  let { out = false, children }: { out?: boolean; children: Snippet } = $props();
</script>

<div class="trace-table-wrap">
  <Table.Root class={['trace-table', out && 'out-table']}>{@render children()}</Table.Root>
</div>

<style>
  .trace-table-wrap :global(.trace-table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }

  .trace-table-wrap :global(.trace-table th),
  .trace-table-wrap :global(.trace-table td) {
    text-align: left;
    padding: 5px 8px;
    border-top: 1px solid color-mix(in srgb, var(--muted-foreground) 12%, transparent);
    vertical-align: top;
  }

  .trace-table-wrap :global(.trace-table th) {
    border-top: none;
    font-size: 11px;
    color: var(--muted-foreground);
    font-weight: 600;
    white-space: nowrap;
  }

  /* Sortable headers (retrieval): click to cycle asc → desc → original. */
  .trace-table-wrap :global(.trace-table th.sortable) {
    cursor: pointer;
    user-select: none;
  }

  .trace-table-wrap :global(.trace-table th.sortable:hover) {
    color: var(--foreground);
  }

  /* Wide rows are hard to track across the table — highlight the whole row on hover. */
  .trace-table-wrap :global(.trace-table tbody tr:hover td) {
    background: color-mix(in srgb, var(--primary) 24%, transparent);
  }

  .trace-table-wrap :global(.trace-table .num) {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .trace-table-wrap :global(.trace-table .fact) {
    min-width: 240px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .trace-table-wrap :global(.trace-table .entity) {
    font-weight: 600;
    white-space: nowrap;
  }

  .trace-table-wrap :global(.trace-table .rel),
  .trace-table-wrap :global(.trace-table .temporal),
  .trace-table-wrap :global(.trace-table .uuid) {
    white-space: nowrap;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
  }

  .trace-table-wrap :global(.trace-table .from) {
    white-space: nowrap;
  }

  .trace-table-wrap :global(.trace-table .vstate) {
    text-align: center;
    white-space: nowrap;
  }

  /* "Strike dropped" rows (retrieval) — didn't survive to the lane's final result set. The
     validity pill stays legible because <ValidityPill> sets its own text-decoration: none. */
  .trace-table-wrap :global(.trace-table tr.struck td) {
    color: var(--muted-foreground);
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--muted-foreground) 55%, transparent);
  }

  /* Structured stage output (ingest): cells wrap (facts/summaries can be long); the leading
     #/key column stays compact. */
  .trace-table-wrap :global(.trace-table.out-table .cell) {
    white-space: pre-wrap;
    word-break: break-word;
    max-width: 520px;
  }

  .trace-table-wrap :global(.trace-table.out-table .kv-key) {
    white-space: nowrap;
    font-weight: 600;
    color: var(--muted-foreground);
    vertical-align: top;
  }

  /* Dedup merge map: center the → arrow column. */
  .trace-table-wrap :global(.trace-table.out-table .arrow-col) {
    text-align: center;
    color: var(--muted-foreground);
    width: 1.5rem;
  }
</style>
