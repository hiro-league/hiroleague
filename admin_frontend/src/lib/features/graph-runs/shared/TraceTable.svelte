<script lang="ts">
  import type { Snippet } from 'svelte';

  // Shared dense-table shell for the trace dialogs — owns the `.trace-table*` styling that was
  // duplicated ~verbatim in both. Callers pass their own `<thead>`/`<tbody>` (columns diverge per
  // lane/stage), so the cell rules use `:global()` — but anchored under this component's scoped
  // `.trace-table`, so they never leak app-wide.
  //   `out` → the structured-output variant (ingest stage tables: wrapping `.cell` / `.kv-key`).
  let { out = false, children }: { out?: boolean; children: Snippet } = $props();
</script>

<div class="trace-table-wrap">
  <table class="trace-table" class:out-table={out}>{@render children()}</table>
</div>

<style>
  .trace-table-wrap {
    overflow-x: auto;
  }

  .trace-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }

  .trace-table :global(th),
  .trace-table :global(td) {
    text-align: left;
    padding: 5px 8px;
    border-top: 1px solid color-mix(in srgb, var(--muted-foreground) 12%, transparent);
    vertical-align: top;
  }

  .trace-table :global(th) {
    border-top: none;
    font-size: 11px;
    color: var(--muted-foreground);
    font-weight: 600;
    white-space: nowrap;
  }

  /* Sortable headers (retrieval): click to cycle asc → desc → original. */
  .trace-table :global(th.sortable) {
    cursor: pointer;
    user-select: none;
  }

  .trace-table :global(th.sortable:hover) {
    color: var(--foreground);
  }

  /* Wide rows are hard to track across the table — highlight the whole row on hover. */
  .trace-table :global(tbody tr:hover td) {
    background: color-mix(in srgb, var(--primary) 24%, transparent);
  }

  .trace-table :global(.num) {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .trace-table :global(.fact) {
    min-width: 240px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .trace-table :global(.entity) {
    font-weight: 600;
    white-space: nowrap;
  }

  .trace-table :global(.rel),
  .trace-table :global(.temporal),
  .trace-table :global(.uuid) {
    white-space: nowrap;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
  }

  .trace-table :global(.from) {
    white-space: nowrap;
  }

  .trace-table :global(.vstate) {
    text-align: center;
    white-space: nowrap;
  }

  /* "Strike dropped" rows (retrieval) — didn't survive to the lane's final result set. The
     validity pill stays legible because <ValidityPill> sets its own text-decoration: none. */
  .trace-table :global(tr.struck td) {
    color: var(--muted-foreground);
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--muted-foreground) 55%, transparent);
  }

  /* Structured stage output (ingest): cells wrap (facts/summaries can be long); the leading
     #/key column stays compact. */
  .trace-table.out-table :global(.cell) {
    white-space: pre-wrap;
    word-break: break-word;
    max-width: 520px;
  }

  .trace-table.out-table :global(.kv-key) {
    white-space: nowrap;
    font-weight: 600;
    color: var(--muted-foreground);
    vertical-align: top;
  }

  /* Dedup merge map: center the → arrow column. */
  .trace-table.out-table :global(.arrow-col) {
    text-align: center;
    color: var(--muted-foreground);
    width: 1.5rem;
  }
</style>
