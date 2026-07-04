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
  import { onMount } from 'svelte';
  import { PREF_KEYS } from '$lib/preferences/keys';
  import { readLocalNumber, writeLocalNumber } from '$lib/preferences/storage';

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

  // Node detail panel is a right-side OVERLAY (doesn't squeeze the table) whose width the user can
  // drag from its left edge; the width persists across reloads (localStorage). Clamped so it can't
  // shrink past legibility or swallow the whole table.
  const DETAIL_WIDTH_DEFAULT = 360;
  const DETAIL_WIDTH_MIN = 280;
  const DETAIL_WIDTH_MAX = 900;
  const DETAIL_WIDTH_STEP = 24; // keyboard resize increment

  let detailWidth = $state(DETAIL_WIDTH_DEFAULT);
  let resizing = $state(false);
  let resizeStartX = 0;
  let resizeStartW = 0;

  onMount(() => {
    detailWidth = clampDetailWidth(
      readLocalNumber(PREF_KEYS.graphRunsNodeDetailWidth, DETAIL_WIDTH_DEFAULT)
    );
  });

  function clampDetailWidth(w: number): number {
    return Math.max(DETAIL_WIDTH_MIN, Math.min(DETAIL_WIDTH_MAX, Math.round(w)));
  }

  function persistDetailWidth() {
    writeLocalNumber(PREF_KEYS.graphRunsNodeDetailWidth, detailWidth);
  }

  function onResizeStart(event: PointerEvent) {
    resizing = true;
    resizeStartX = event.clientX;
    resizeStartW = detailWidth;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function onResizeMove(event: PointerEvent) {
    if (!resizing) return;
    // The panel is pinned to the right, so dragging the LEFT handle leftward (clientX decreasing)
    // widens it.
    detailWidth = clampDetailWidth(resizeStartW + (resizeStartX - event.clientX));
  }

  function onResizeEnd(event: PointerEvent) {
    if (!resizing) return;
    resizing = false;
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
    persistDetailWidth();
  }

  function onResizeKeydown(event: KeyboardEvent) {
    const dir = event.key === 'ArrowLeft' ? 1 : event.key === 'ArrowRight' ? -1 : 0;
    if (dir === 0) return;
    event.preventDefault();
    detailWidth = clampDetailWidth(detailWidth + dir * DETAIL_WIDTH_STEP);
    persistDetailWidth();
  }
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

    <div class="run-detail-node-grid" style="--node-detail-w: {detailWidth}px">
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
        <!-- Overlay: floats over the RIGHT of the (full-width) table instead of taking a grid column,
             so opening it never squeezes the table. The inner element stays sticky-pinned on scroll. -->
        <div class="node-detail-overlay" class:node-detail-overlay--resizing={resizing}>
          <div class="node-detail-sticky">
            <!-- Focusable splitter: role=separator + aria-valuenow is the correct pattern; the
                 linter just doesn't treat it as interactive (same as LogsTablePanel's scroller). -->
            <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
            <div
              class="node-detail-resizer"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize node details panel"
              aria-valuemin={DETAIL_WIDTH_MIN}
              aria-valuemax={DETAIL_WIDTH_MAX}
              aria-valuenow={detailWidth}
              tabindex="0"
              title="Drag to resize (← / → to nudge)"
              onpointerdown={onResizeStart}
              onpointermove={onResizeMove}
              onpointerup={onResizeEnd}
              onpointercancel={onResizeEnd}
              onkeydown={onResizeKeydown}
            ></div>
            <GraphRunsNodeDetailPanel
              row={nodeDetailRow}
              fields={nodeDetailFieldList}
              onClose={onCloseNodeDetails}
            />
          </div>
        </div>
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
    /* ALWAYS single column: the table keeps full width; the detail panel floats OVER it as an
       absolute overlay (below) rather than taking a second column that squeezes the table. */
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    min-height: 0;
    min-width: 0;
    align-items: stretch;
    position: relative; /* containing block for the absolute detail overlay */
  }

  /* --- Node detail: right-side OVERLAY (does not squeeze the table) --------------------------- */

  /* Narrow screens: the overlay degrades to normal in-flow stacking (a row under the table), full
     width, no resize handle — the pre-overlay behavior. */
  .node-detail-overlay {
    min-width: 0;
  }

  .node-detail-sticky {
    display: flex;
    align-items: stretch;
    min-width: 0;
  }

  .node-detail-sticky > :global(.node-detail-panel) {
    flex: 1 1 auto;
    min-width: 0;
  }

  .node-detail-resizer {
    display: none;
  }

  /* While dragging, suppress text selection (pointer capture already routes moves to the handle). */
  .node-detail-overlay--resizing {
    user-select: none;
  }

  @media (min-width: 760px) {
    /* Float the panel over the RIGHT edge of the table. inset top/bottom:0 makes the absolute box
       span the node grid's height (= the page-scrolled table), so the sticky inner can travel the
       full scroll range just like before. */
    .node-detail-overlay {
      position: absolute;
      inset: 0 0 0 auto;
      width: var(--node-detail-w, 360px);
      z-index: 5;
      /* Transparent gutters above/below the sticky panel let the table rows underneath stay
         clickable; the panel + handle re-enable pointer events. */
      pointer-events: none;
    }

    .node-detail-sticky {
      pointer-events: auto;
      /* Stay pinned beside the page-scrolled nodes table (top matches the sticky chrome offset). */
      position: sticky;
      top: calc(
        4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + 0.75rem
      );
      min-height: 340px;
      /* Fill the viewport height left below the sticky chrome (grows as the header compacts on
         scroll-up). Trailing 1.5rem = the 0.75rem sticky-top gap + 0.75rem bottom breathing room. */
      max-height: calc(
        100dvh - 4rem - var(--admin-page-header-h, 0px) - var(--admin-page-sticky-toolbar-h, 0px) -
          1.5rem
      );
    }

    .node-detail-sticky > :global(.node-detail-panel) {
      max-height: 100%;
    }

    /* Left-edge drag handle to resize the overlay width. */
    .node-detail-resizer {
      display: block;
      flex: 0 0 auto;
      width: 10px;
      margin-right: -4px; /* sit the grip on the panel's left seam */
      cursor: ew-resize;
      touch-action: none;
      align-self: stretch;
      background: transparent;
    }

    .node-detail-resizer::before {
      content: '';
      display: block;
      width: 2px;
      height: 100%;
      margin: 0 auto;
      border-radius: 2px;
      background: color-mix(in srgb, var(--border) 70%, transparent);
      transition: background 100ms ease;
    }

    .node-detail-resizer:hover::before,
    .node-detail-resizer:focus-visible::before,
    .node-detail-overlay--resizing .node-detail-resizer::before {
      background: var(--primary);
    }

    .node-detail-resizer:focus-visible {
      outline: 2px solid var(--primary);
      outline-offset: 1px;
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
