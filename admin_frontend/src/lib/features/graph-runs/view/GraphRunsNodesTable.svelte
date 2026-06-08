<script lang="ts">
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { fieldLabel, formatLedgerField, isGraphNodeSubstep } from '../graph-runs-pure';

  let {
    timeline,
    nodeFieldList,
    selectedNodeRowId,
    traceStepIds = new Set<number>(),
    ingestTraceStepIds = new Set<number>(),
    onToggleNodeRow,
    onOpenNodeDetails,
    onOpenRetrievalTrace,
    onOpenIngestTrace
  }: {
    timeline: GraphLedgerRow[];
    nodeFieldList: readonly (keyof GraphLedgerRow)[];
    selectedNodeRowId: string | null;
    /** Step indexes that have a recorded retrieval trace — drives the per-row marker. */
    traceStepIds?: Set<number>;
    /** Step indexes (episode rows) that have a recorded ingest trace — drives its marker. */
    ingestTraceStepIds?: Set<number>;
    onToggleNodeRow: (compositeRowId: string) => void;
    onOpenNodeDetails: (row: GraphLedgerRow) => void;
    onOpenRetrievalTrace?: (row: GraphLedgerRow) => void;
    onOpenIngestTrace?: (row: GraphLedgerRow) => void;
  } = $props();

  /** True when ``row`` is a top-level step (not a nested sub-step). Sub-steps share the
   *  parent's step index, so gating on a falsy sub_step avoids duplicate markers. */
  function isParentStep(row: GraphLedgerRow): boolean {
    const sub = row.sub_step;
    return sub === '' || sub === 0 || sub === null || sub === undefined;
  }

  function stepOf(row: GraphLedgerRow): number {
    return typeof row.step_index === 'number' ? row.step_index : Number(row.step_index);
  }

  /** Marker shows on the PARENT row of any step that has a retrieval-trace sidecar
   *  (``graph_expand`` for knowledge, ``memory_recall`` for memory). */
  function rowHasTrace(row: GraphLedgerRow): boolean {
    if (!onOpenRetrievalTrace || !isParentStep(row)) return false;
    const step = stepOf(row);
    return Number.isFinite(step) && traceStepIds.has(step);
  }

  /** Ingest-trace marker on the PARENT episode row (``knowledge_graph_ingest/episode``). A
   *  run is either an ingest run or a retrieval run, so the two markers never collide. */
  function rowHasIngestTrace(row: GraphLedgerRow): boolean {
    if (!onOpenIngestTrace || !isParentStep(row)) return false;
    const step = stepOf(row);
    return Number.isFinite(step) && ingestTraceStepIds.has(step);
  }
</script>

<div class="nodes-table-panel min-w-0">
  <AdminTableShell density="dense" stickyHead class="nodes-scroll">
    <thead>
      <tr>
        {#each nodeFieldList as field (field)}
          <th title={field}>{fieldLabel(field)}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each timeline as row (row.id)}
        <tr
          class="nodes-table__data-row"
          class:nodes-table__data-row--selected={selectedNodeRowId === row.id}
          class:substep={isGraphNodeSubstep(row.node)}
          tabindex="0"
          aria-selected={selectedNodeRowId === row.id ? 'true' : 'false'}
          onclick={() => onToggleNodeRow(row.id)}
          ondblclick={() => onOpenNodeDetails(row)}
          onkeydown={(ev) => {
            if (ev.key !== 'Enter' && ev.key !== ' ') return;
            ev.preventDefault();
            onToggleNodeRow(row.id);
          }}
        >
          {#each nodeFieldList as field (field)}
            <td class="font-mono">
              {#if field === 'node' && rowHasTrace(row)}
                <span class="node-cell">
                  <span>{formatLedgerField(field, row)}</span>
                  <button
                    type="button"
                    class="trace-marker"
                    title="Open retrieval stage trace (candidate legs · hop · rank · temporal)"
                    aria-label="Open retrieval stage trace"
                    onclick={(ev) => {
                      ev.stopPropagation();
                      onOpenRetrievalTrace?.(row);
                    }}
                  >
                    {'\u2317'}
                  </button>
                </span>
              {:else if field === 'node' && rowHasIngestTrace(row)}
                <span class="node-cell">
                  <span>{formatLedgerField(field, row)}</span>
                  <button
                    type="button"
                    class="trace-marker"
                    title="Open ingest stage trace (extract · resolve · facts · dates · summarize)"
                    aria-label="Open ingest stage trace"
                    onclick={(ev) => {
                      ev.stopPropagation();
                      onOpenIngestTrace?.(row);
                    }}
                  >
                    {'\u29C9'}
                  </button>
                </span>
              {:else}
                {formatLedgerField(field, row)}
              {/if}
            </td>
          {/each}
        </tr>
      {:else}
        <tr class="placeholder-row">
          <td colspan={nodeFieldList.length}>No node rows loaded.</td>
        </tr>
      {/each}
    </tbody>
  </AdminTableShell>
</div>

<style>
  .nodes-table-panel {
    min-width: 0;
  }

  .nodes-table__data-row {
    cursor: pointer;
    outline: none;
    transition:
      background-color 80ms ease,
      box-shadow 80ms ease;
  }

  .nodes-table__data-row:hover:not(.nodes-table__data-row--selected) {
    background: color-mix(in srgb, var(--muted-foreground) 12%, transparent);
  }

  .nodes-table__data-row.nodes-table__data-row--selected {
    background: color-mix(in srgb, var(--primary) 18%, transparent);
    box-shadow: inset 4px 0 0 var(--primary);
  }

  /* Nested sub-step rows (tools/*, knowledge/*) read as children via an indent on the step cell
     plus their ``4.1`` numbering — the previous primary-tinted highlight was removed. */
  .nodes-table__data-row.substep td:first-child {
    padding-left: 1.5rem;
  }

  .nodes-table__data-row:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
  }

  tr.placeholder-row td {
    text-align: center;
    color: var(--muted-foreground);
    white-space: normal;
    padding: 16px;
  }

  .node-cell {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .trace-marker {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    padding: 0;
    border: 1px solid color-mix(in srgb, var(--primary) 45%, transparent);
    border-radius: 4px;
    background: color-mix(in srgb, var(--primary) 12%, transparent);
    color: var(--primary);
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
  }

  .trace-marker:hover {
    background: color-mix(in srgb, var(--primary) 24%, transparent);
  }

  .trace-marker:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 1px;
  }
</style>
