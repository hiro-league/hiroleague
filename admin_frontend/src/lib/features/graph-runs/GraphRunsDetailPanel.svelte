<script lang="ts">
  import type { CharacterDetail } from '$lib/api/characters';
  import type {
    GraphLedgerRow,
    IngestTraceRecord,
    RetrievalTraceRecord
  } from '$lib/api/graph-runs';
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
  import GraphRunsRetrievalTraceDialog from './GraphRunsRetrievalTraceDialog.svelte';
  import GraphRunsIngestTraceDialog from './GraphRunsIngestTraceDialog.svelte';
  import EvalRowDetailDialog from '$lib/features/eval/answers/EvalRowDetailDialog.svelte';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { RetrievalTraceDialogController } from './state/retrieval-trace-dialog.svelte';

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
    traceStepIds,
    activeRetrievalTrace,
    ingestTraceStepIds,
    activeIngestTrace,
    onToggleNodeRow,
    onOpenNodeDetails,
    onCloseNodeDetails,
    onOpenRetrievalTrace,
    onCloseRetrievalTrace,
    onOpenIngestTrace,
    onCloseIngestTrace,
    ingestTraceHasPrev,
    ingestTraceHasNext,
    ingestTraceNavIndex,
    ingestTraceNavTotal,
    onPrevIngestTrace,
    onNextIngestTrace,
    activeEvalRow,
    evalRowLegColumns,
    evalRowTraces,
    onOpenEvalRow,
    onCloseEvalRow,
    onOpenRetrievalLoop
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
    traceStepIds: Set<number>;
    activeRetrievalTrace: RetrievalTraceRecord | null;
    ingestTraceStepIds: Set<number>;
    activeIngestTrace: IngestTraceRecord | null;
    onToggleNodeRow: (compositeRowId: string) => void;
    onOpenNodeDetails: (row: GraphLedgerRow) => void;
    onCloseNodeDetails: () => void;
    onOpenRetrievalTrace: (row: GraphLedgerRow) => void;
    onCloseRetrievalTrace: () => void;
    onOpenIngestTrace: (row: GraphLedgerRow) => void;
    onCloseIngestTrace: () => void;
    ingestTraceHasPrev: boolean;
    ingestTraceHasNext: boolean;
    ingestTraceNavIndex: number;
    ingestTraceNavTotal: number;
    onPrevIngestTrace: () => void;
    onNextIngestTrace: () => void;
    /** Eval-detail bridge — the resolved row (null when closed), its leg columns, the stacked
     *  per-search trace controller, and open/close handlers for the `memory_recall` marker. */
    activeEvalRow: EvalRow | null;
    evalRowLegColumns: string[];
    evalRowTraces: RetrievalTraceDialogController;
    onOpenEvalRow: (row: GraphLedgerRow) => void;
    onCloseEvalRow: () => void;
    /** Chat retrieval-loop bridge (P5 part 2) — opens the SAME eval detail dialog (`activeEvalRow`)
     *  from a CHAT `memory_recall` node's trajectory marker; it closes via `onCloseEvalRow`. */
    onOpenRetrievalLoop: (row: GraphLedgerRow) => void;
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
        {traceStepIds}
        {ingestTraceStepIds}
        {onToggleNodeRow}
        {onOpenNodeDetails}
        {onOpenRetrievalTrace}
        {onOpenIngestTrace}
        {onOpenEvalRow}
        {onOpenRetrievalLoop}
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

<GraphRunsRetrievalTraceDialog trace={activeRetrievalTrace} onClose={onCloseRetrievalTrace} />

<!-- Eval-detail bridge: the rich per-question dialog (reused from the Eval panel) opened from a
     memory_recall node, plus the stacked per-search trace dialog its Trajectory tab opens. -->
<EvalRowDetailDialog
  row={activeEvalRow}
  legColumns={evalRowLegColumns}
  searchTerm=""
  recalledTerm=""
  traces={evalRowTraces}
  onClose={onCloseEvalRow}
/>
<GraphRunsRetrievalTraceDialog
  trace={evalRowTraces.activeTrace}
  idealAnswer={evalRowTraces.activeTraceIdeal}
  llmAnswer={evalRowTraces.activeTraceAnswer}
  onClose={evalRowTraces.closeTrace}
/>

<GraphRunsIngestTraceDialog
  trace={activeIngestTrace}
  onClose={onCloseIngestTrace}
  hasPrev={ingestTraceHasPrev}
  hasNext={ingestTraceHasNext}
  navIndex={ingestTraceNavIndex}
  navTotal={ingestTraceNavTotal}
  onPrev={onPrevIngestTrace}
  onNext={onNextIngestTrace}
/>

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

  /* No scroll-past-end padding on the table column. The side panel (col 2) is already capped to the
     remaining viewport height, so it needs no extra-tall cell to pin against — and the old padding
     made the page scroll the short node table up under its sticky header into empty space, hiding
     all the rows. Without it the node grid lands flush under the sticky chrome with every row
     visible and no phantom scroll. */

  /* With the side panel open the table column is narrow; clip the wide ledger row's horizontal
     overflow so it doesn't bleed under the (semi-transparent) panel. `clip` contains it WITHOUT
     creating a scroll container, so the page-sticky header and sticky panel keep working. The
     clipped right-hand columns are exactly the fields the open detail panel already shows. */
  .run-detail-node-grid--with-panel > :global(.nodes-table-panel) {
    overflow-x: clip;
  }

  .run-detail-node-grid--with-panel {
    grid-template-columns: minmax(0, 1fr);
  }

  .run-detail-node-grid > :global(.node-detail-panel) {
    /* Stay pinned beside the page-scrolled nodes table (top matches the sticky chrome offset). */
    position: sticky;
    top: calc(
      4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + 0.75rem
    );
    align-self: start;
    min-height: 340px;
    /* Fill the viewport height left below the sticky chrome instead of a fixed 70vh/720px cap, so
       the panel grows to use the remaining space — and grows further as the header compacts on
       scroll-up (var(--admin-page-header-h) shrinks when pinned). The trailing 1.5rem = the 0.75rem
       sticky-top gap above + a matching 0.75rem breathing room at the bottom. */
    max-height: calc(
      100dvh - 4rem - var(--admin-page-header-h, 0px) - var(--admin-page-sticky-toolbar-h, 0px) -
        1.5rem
    );
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
