<script lang="ts">
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import { fieldLabel, formatLedgerField, isGraphNodeSubstep } from '../graph-runs-pure';
  import GraphRunsTableShell from './GraphRunsTableShell.svelte';

  let {
    timeline,
    nodeFieldList,
    selectedNodeRowId,
    onToggleNodeRow,
    onOpenNodeDetails
  }: {
    timeline: GraphLedgerRow[];
    nodeFieldList: readonly (keyof GraphLedgerRow)[];
    selectedNodeRowId: string | null;
    onToggleNodeRow: (compositeRowId: string) => void;
    onOpenNodeDetails: (row: GraphLedgerRow) => void;
  } = $props();
</script>

<div class="nodes-table-panel">
  <p class="section-label">Nodes</p>
  <GraphRunsTableShell class="nodes-scroll">
    <table class="nodes-table">
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
              <td class="mono">{formatLedgerField(field, row)}</td>
            {/each}
          </tr>
        {:else}
          <tr class="placeholder-row">
            <td colspan={nodeFieldList.length}>No node rows loaded.</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </GraphRunsTableShell>
</div>

<style>
  .nodes-table-panel {
    min-width: 0;
  }

  .section-label {
    margin-top: 8px;
    margin-bottom: 0;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground, #64748b);
  }

  /* `GraphRunsTableShell` root — class is composed as `gr-table-shell nodes-scroll`. */
  :global(.gr-table-shell.nodes-scroll) {
    max-height: min(70vh, 720px);
  }

  .nodes-table tbody tr.nodes-table__data-row {
    cursor: pointer;
    outline: none;
    transition:
      background-color 80ms ease,
      box-shadow 80ms ease;
  }

  .nodes-table tbody tr.nodes-table__data-row.substep {
    background: color-mix(in srgb, var(--primary, #0ea5e9) 8%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row:hover:not(.nodes-table__data-row--selected) {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 12%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row.substep:hover:not(.nodes-table__data-row--selected) {
    background: color-mix(in srgb, var(--primary, #0ea5e9) 16%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row.nodes-table__data-row--selected {
    background: color-mix(in srgb, var(--primary, #0369a1) 18%, transparent);
    box-shadow: inset 4px 0 0 var(--primary, #0ea5e9);
  }

  .nodes-table tbody tr.nodes-table__data-row.substep.nodes-table__data-row--selected {
    background: color-mix(in srgb, var(--primary, #0369a1) 22%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row:focus-visible {
    outline: 2px solid var(--primary, #0369a1);
    outline-offset: -2px;
  }

  .mono {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  }

  tr.placeholder-row td {
    text-align: center;
    color: var(--muted-foreground, #64748b);
    white-space: normal;
    padding: 16px;
  }
</style>
