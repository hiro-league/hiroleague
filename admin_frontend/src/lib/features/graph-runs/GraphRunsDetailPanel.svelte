<script lang="ts">
  import type { CharacterDetail } from '$lib/api/characters';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import {
    graphRunTabId,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_SUBTAB_IDS,
    isRunDetailPane,
    type ActivePane
  } from './graph-runs-pure';
  import GraphRunsRunAggregateMetrics from './view/GraphRunsRunAggregateMetrics.svelte';
  import GraphRunsRunDetailHeading from './view/GraphRunsRunDetailHeading.svelte';
  import GraphRunsNodesTable from './view/GraphRunsNodesTable.svelte';
  import GraphRunsNodeDetailPanel from './GraphRunsNodeDetailPanel.svelte';

  let {
    activePane,
    runDetailCardsExpanded,
    activeRunAggregate,
    langsmithUrlForActive,
    runIdentitySource,
    titleCharacter,
    runTitlePrimary,
    runTitleSubtitle,
    runIdFirstCardDisplay,
    toolbarElapsedLabel,
    toolbarTotalCostLabel,
    timeline,
    selectedNodeRowId,
    nodeDetailRow,
    headerFieldList,
    nodeFieldList,
    nodeDetailFieldList,
    onToggleNodeRow,
    onOpenNodeDetails,
    onCloseNodeDetails
  }: {
    activePane: ActivePane;
    runDetailCardsExpanded: boolean;
    activeRunAggregate: GraphLedgerRow | null;
    langsmithUrlForActive: string | null;
    runIdentitySource: GraphLedgerRow | null;
    titleCharacter: CharacterDetail | null;
    runTitlePrimary: string;
    runTitleSubtitle: string;
    runIdFirstCardDisplay: string;
    toolbarElapsedLabel: string;
    toolbarTotalCostLabel: string;
    timeline: GraphLedgerRow[];
    selectedNodeRowId: string | null;
    nodeDetailRow: GraphLedgerRow | null;
    headerFieldList: readonly (keyof GraphLedgerRow)[];
    nodeFieldList: readonly (keyof GraphLedgerRow)[];
    nodeDetailFieldList: readonly (keyof GraphLedgerRow)[];
    onToggleNodeRow: (compositeRowId: string) => void;
    onOpenNodeDetails: (row: GraphLedgerRow) => void;
    onCloseNodeDetails: () => void;
  } = $props();

  const detailHidden = $derived(!isRunDetailPane(activePane));
  const detailAriaLabelledby = $derived(
    isRunDetailPane(activePane) ? graphRunTabId(activePane) : GRAPH_RUNS_SUBTAB_IDS.browse
  );
</script>

<div
  id={GRAPH_RUNS_PANEL_IDS.detail}
  class="graph-runs-detail-panel min-w-0"
  role="tabpanel"
  aria-labelledby={detailAriaLabelledby}
  hidden={detailHidden}
>
  <div class="run-detail">
    <div
      id="run-detail-cards-flow"
      class="run-detail-cards-flow"
      class:run-detail-cards-flow--collapsed={!runDetailCardsExpanded}
      role="region"
      aria-label="Run summary — previews, timing, metrics, ledger"
    >
      <GraphRunsRunDetailHeading
        {activePane}
        {activeRunAggregate}
        {langsmithUrlForActive}
        {runIdentitySource}
        {titleCharacter}
        {runTitlePrimary}
        {runTitleSubtitle}
        {runIdFirstCardDisplay}
      />
      {#if activeRunAggregate}
        <GraphRunsRunAggregateMetrics
          {activeRunAggregate}
          {toolbarElapsedLabel}
          {toolbarTotalCostLabel}
          {headerFieldList}
        />
      {/if}
    </div>

    {#if !activeRunAggregate}
      <p class="warn">
        No aggregate (<code class="mono">row_kind=run</code>) line found for this run in the ledger yet.
        Node timeline below still loads when present.
      </p>
    {/if}

    <div
      class="run-detail-node-grid"
      class:run-detail-node-grid--with-panel={nodeDetailRow !== null}
    >
      <GraphRunsNodesTable
        {timeline}
        {nodeFieldList}
        {selectedNodeRowId}
        {onToggleNodeRow}
        {onOpenNodeDetails}
      />

      {#if nodeDetailRow}
        <GraphRunsNodeDetailPanel
          row={nodeDetailRow}
          fields={nodeDetailFieldList}
          onClose={onCloseNodeDetails}
        />
      {/if}
    </div>
  </div>
</div>

<style>
  /* Child slices use their own scoped classes; `:global` keeps flex + collapse rules on the flow host. */
  .run-detail-cards-flow--collapsed
    > :global(.run-metric-card:not(.run-metric-card--preview):not(.run-metric-card--elapsed-total)),
  .run-detail-cards-flow--collapsed > :global(.run-header-grid) {
    display: none;
  }

  .run-detail-cards-flow > :global(.run-header-grid) {
    flex: 1 1 100%;
    min-width: 0;
    max-width: 100%;
    align-self: stretch;
    box-sizing: border-box;
  }

  .run-detail {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .run-detail-cards-flow {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 12px;
    min-width: 0;
  }

  .run-detail-cards-flow > :global(.run-detail-toolbar) {
    flex: 1 1 minmax(260px, 100%);
  }

  .run-detail-cards-flow > :global(.run-metric-card) {
    flex: 1 1 220px;
    max-width: 100%;
    align-self: stretch;
    box-sizing: border-box;
  }

  .run-detail-cards-flow > :global(.run-metric-card--preview) {
    flex: 1 1 minmax(200px, 340px);
  }

  .run-detail-cards-flow > :global(.run-metric-card--tokens),
  .run-detail-cards-flow > :global(.run-metric-card--speech) {
    flex: 1 1 minmax(260px, 100%);
  }

  .run-detail-node-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    min-height: 0;
    min-width: 0;
    align-items: stretch;
  }

  .run-detail-node-grid--with-panel {
    grid-template-columns: minmax(0, 1fr);
  }

  .run-detail-node-grid > :global(.node-detail-panel) {
    min-height: 340px;
    max-height: min(70vh, 720px);
  }

  @media (min-width: 760px) {
    .run-detail-node-grid--with-panel {
      grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
    }
  }

  .mono {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  }

  .warn {
    margin: 0;
    padding: 10px;
    border-radius: 8px;
    border: 1px solid color-mix(in srgb, #f97316 40%, transparent);
    background: color-mix(in srgb, #f97316 10%, transparent);
    color: var(--foreground, #0f172a);
    font-size: 13px;
  }
</style>
