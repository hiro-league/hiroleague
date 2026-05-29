<script lang="ts">
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { fieldLabel, formatLedgerField, isGraphNodeSubstep } from '../graph-runs-pure';

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

<div class="nodes-table-panel min-w-0">
  <p class="section-label">Nodes</p>
  <AdminTableShell density="dense" maxBodyHeight="min(70vh, 720px)" class="nodes-scroll">
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
            <td class="font-mono">{formatLedgerField(field, row)}</td>
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

  .section-label {
    margin-top: 8px;
    margin-bottom: 0;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground, #64748b);
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
</style>
