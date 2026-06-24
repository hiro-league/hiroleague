<!--
  Questions/Answers pane — a sticky toolbar (run-selection + search/filters + LoCoMo export) over
  the flat results table (EvalResultsTable) and the still-unanswered bank questions
  (EvalNotRunList). Owns ALL answer-view state: filters, sort, row expansion, and the sticky
  controls-bar height var the table's sticky thead pins beneath.
-->
<script lang="ts">
  import { Download, FoldVertical, ListChecks, ListX, LoaderCircle, UnfoldVertical } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { setupStickyHeightVar } from '$lib/styling/sticky-height';
  import { ADMIN_SELECT_SM } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import EvalResultsTable from '$lib/features/eval/answers/EvalResultsTable.svelte';
  import EvalRowDetailDialog from '$lib/features/eval/answers/EvalRowDetailDialog.svelte';
  import EvalNotRunList from '$lib/features/eval/answers/EvalNotRunList.svelte';
  import { useTableSort } from '$lib/components/page/table/use-table-sort.svelte';
  import { distinctOptionsWithSentinel } from '$lib/components/page/table/distinct-options';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import {
    EVAL_ANSWER_FILTER_KEYS,
    evalAnswerFilterOrAll,
    evalAnswerFiltersActive
  } from '$lib/features/eval/shared/eval-answer-filters';
  import {
    rowHaystack,
    rowMatchesFlag,
    rowMatchesMark,
    sortGroupRows,
    type AnsFlag,
    type AnsMark,
    type AnsSortKey
  } from '$lib/features/eval/shared/eval-derive';
  import { matchesQuery, rowMatches } from '$lib/search/match';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import {
    decompositionRate,
    turnsPerQuestionHistogram
  } from '$lib/features/eval/answers/eval-trajectory-controller.svelte';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    traces: EvalTraces;
  }
  let { eval_, cfg, traces }: Props = $props();

  type EvalAnswerSortColumn = Exclude<AnsSortKey, 'none'>;

  const sort = useTableSort<EvalAnswerSortColumn>({
    defaultBy: 'time',
    defaultDirection: 'none',
    allowed: ['recall', 'time', 'difficulty', 'evidence', 'mark'],
    threeState: true
  });
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Toolbar progress (memory recalled/elapsed live on the retrieval-loop bar once complete).
  const resultsSummary = $derived.by(() => {
    if (eval_.summary) {
      if (eval_.summary.track === 'memory') return '';
      const g = eval_.summary.gate;
      const label = g === 'proceed' ? '✅ PROCEED' : g === 'pivot' ? '❌ PIVOT' : 'Done';
      return `${label} · ${eval_.summary.elapsed_ms}ms`;
    }
    if (eval_.rows.length > 0) return `${eval_.rows.length}/${eval_.totalQuestions}`;
    return '';
  });

  const memoryRunSummary = $derived.by(() => {
    if (eval_.summary?.track !== 'memory') return '';
    return `recalled ${eval_.summary.recalled_for ?? 0}/${eval_.summary.total_questions} · ${eval_.summary.elapsed_ms}ms`;
  });

  // Sticky controls-bar height → CSS var so the results table's sticky thead pins beneath it.
  // Conditionally mounted, so the $effect (re)observes when the bound element appears.
  let aControlsEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    if (!aControlsEl) return;
    return setupStickyHeightVar(aControlsEl, '--admin-eval-acontrols-h', { trackScroll: true });
  });

  // Per-row expansion (full answers). Keyed by question index; reassigned on mutation so Svelte
  // tracks the Set.
  let expandedRows = $state<Set<number>>(new Set());
  function toggleRow(index: number) {
    const next = new Set(expandedRows);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    expandedRows = next;
  }

  // Bulk expand/collapse tick — applied by EvalClampAnswer when folds open.
  let bulkTextOpen = $state(false);
  let bulkTextTick = $state(0);

  // The row whose giant detail dialog is open (null = closed). Opened from the ANSWER TYPE cell
  // or the slim fold's "Open details" button.
  let detailRow = $state<EvalRow | null>(null);

  // --- Filters (URL-synced via `ans_*` query params) ------------------------------------------
  const tableFilters = useTableFilters({
    keys: EVAL_ANSWER_FILTER_KEYS,
    urlSync: true
  });
  const ansSearch = $derived(tableFilters.filters.ans_q);
  const ansSearchRecalled = $derived(tableFilters.filters.ans_rec === '1');
  const ansCategory = $derived(evalAnswerFilterOrAll(tableFilters.filters.ans_cat));
  type QDifficulty = 'all' | 'medium' | 'hard' | 'very_hard' | 'unspecified';
  const ansDifficulty = $derived(evalAnswerFilterOrAll(tableFilters.filters.ans_diff) as QDifficulty);
  const ansFlag = $derived(evalAnswerFilterOrAll(tableFilters.filters.ans_flag) as AnsFlag);
  const ansMark = $derived(evalAnswerFilterOrAll(tableFilters.filters.ans_mark) as AnsMark);
  const recalledTerm = $derived(ansSearchRecalled ? ansSearch : '');
  const ansFiltered = $derived(evalAnswerFiltersActive(tableFilters.filters));
  function resetAnswerFilters() {
    tableFilters.reset();
  }
  function setAnsSearch(value: string) {
    tableFilters.set('ans_q', value);
  }
  function setAnsSearchRecalled(checked: boolean) {
    tableFilters.set('ans_rec', checked ? '1' : '');
  }
  function setAnsCategory(value: string) {
    tableFilters.set('ans_cat', value === 'all' ? '' : value);
  }
  function setAnsDifficulty(value: string) {
    tableFilters.set('ans_diff', value === 'all' ? '' : value);
  }
  function setAnsFlag(value: string) {
    tableFilters.set('ans_flag', value === 'all' ? '' : value);
  }
  function setAnsMark(value: string) {
    tableFilters.set('ans_mark', value === 'all' ? '' : value);
  }
  // Distinct categories among the answer rows (first-seen order) for the type filter dropdown.
  const ansCategoryOptions = $derived(
    distinctOptionsWithSentinel(eval_.rows, (r) => r.category || undefined, { sort: false }).map(
      (o) => o.value
    )
  );
  const filteredAnswerRows = $derived.by(() => {
    const q = ansSearch.trim();
    return eval_.rows.filter((r) => {
      if (ansCategory !== 'all' && (r.category || '') !== ansCategory) return false;
      if (ansDifficulty !== 'all' && (r.difficulty || 'unspecified') !== ansDifficulty) return false;
      if (cfg.showRecallColumn && !rowMatchesFlag(r, ansFlag)) return false;
      if (!rowMatchesMark(r, ansMark)) return false;
      if (q && !matchesQuery(rowHaystack(r, ansSearchRecalled), q)) return false;
      return true;
    });
  });

  // --- Flat results list (sorted) -----------------------------------------------------------
  const resultRows = $derived.by<EvalRow[]>(() => {
    const sorted = [...filteredAnswerRows].sort((a, b) => a.index - b.index);
    return sortGroupRows(sorted, sort.sortBy, sort.direction);
  });

  function expandAllFolds() {
    expandedRows = new Set(resultRows.map((r) => r.index));
    bulkTextOpen = true;
    bulkTextTick += 1;
  }
  function collapseAllFolds() {
    expandedRows = new Set();
    bulkTextOpen = false;
    bulkTextTick += 1;
  }
  const canExpandAllFolds = $derived(resultRows.length > 0);
  const canCollapseAllFolds = $derived(expandedRows.size > 0);

  const retrievalTurnsHistogram = $derived(turnsPerQuestionHistogram(eval_.rows));
  const retrievalDecompositionRate = $derived(decompositionRate(eval_.rows));
  const showRetrievalLoopSummary = $derived(
    cfg.track === 'memory' && eval_.rows.some((row) => row.legs.recall?.retrieval_loop)
  );
  const showMemorySummaryBar = $derived(
    cfg.track === 'memory' && (showRetrievalLoopSummary || memoryRunSummary !== '')
  );

  // --- Table column shape (legs + optional columns) -----------------------------------------
  const legColumns = $derived(eval_.runModes);
  const showDelta = $derived(cfg.showDelta);
  const showRecallCol = $derived(cfg.showRecallColumn);
  const showEvidenceCol = $derived(cfg.showEvidenceColumn);
  // Base 4 = select + #, Type, Question; + legs (1/leg: answer-type for memory, answer for
  // knowledge) + optional recall/evidence/Δ columns + Difficulty + Time. (Ideal moved into the fold.)
  const resultsColspan = $derived(
    4 +
      legColumns.length +
      (showDelta ? 1 : 0) +
      (showRecallCol ? 1 : 0) +
      (showEvidenceCol ? 1 : 0) +
      2
  );

  // --- Not-run questions (full-bank questions with no answered row yet) ----------------------
  const answeredIds = $derived(new Set(eval_.rows.map((r) => r.id)));
  const bankPos = $derived(new Map(eval_.questions.map((q, i) => [q.id, i + 1])));
  const notRunQuestions = $derived.by(() => {
    // Answer-attribute filters (verdict / recall flag) can't match an un-run question → hide the list.
    if (ansMark !== 'all' || ansFlag !== 'all') return [];
    const q = ansSearch.trim();
    return eval_.questions.filter((qRow) => {
      if (answeredIds.has(qRow.id)) return false;
      if (ansCategory !== 'all' && (qRow.category || '') !== ansCategory) return false;
      if (ansDifficulty !== 'all' && (qRow.difficulty || 'unspecified') !== ansDifficulty) return false;
      if (
        q &&
        !rowMatches(qRow, q, (row) => [row.question, row.id, row.category, row.subcategory ?? ''])
      )
        return false;
      return true;
    });
  });

  // Select-all header checkbox targets every question currently visible under the filters.
  const filteredSelectableIds = $derived([
    ...filteredAnswerRows.map((r) => r.id),
    ...notRunQuestions.map((q) => q.id)
  ]);
  const allFilteredSelected = $derived(
    filteredSelectableIds.length > 0 && filteredSelectableIds.every((id) => eval_.isSelected(id))
  );
  const someFilteredSelected = $derived(
    !allFilteredSelected && filteredSelectableIds.some((id) => eval_.isSelected(id))
  );
  function toggleSelectAllFiltered() {
    eval_.setCategorySelected(filteredSelectableIds, !allFilteredSelected);
  }

  const canSelectAllBank = $derived(
    !isBusy && eval_.questions.length > 0 && eval_.selectedCount < eval_.questions.length
  );
  const canClearSelection = $derived(!isBusy && eval_.selectedCount > 0);
</script>

{#if eval_.questions.length === 0}
  <InlineEmptyState message="No questions loaded — pick a corpus on the Execute tab." />
{:else}
  <!-- Sticky controls: run-selection + search/filters + LoCoMo export. -->
  <div
    bind:this={aControlsEl}
    class="sticky z-10 flex flex-wrap items-center gap-2 bg-background py-2 pl-3"
    style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px));"
  >
    <span class="mr-auto font-sans text-xs text-muted-foreground">
      <span class="font-medium text-foreground">{eval_.selectedCount}</span>/{eval_.questions
        .length} selected{#if resultsSummary} · {resultsSummary}{/if}{#if ansFiltered}
        · {filteredAnswerRows.length}/{eval_.rows.length} shown{/if}
    </span>
    <AdminFilterBar class="ml-auto items-center gap-2">
      <SearchInput
        variant="inline"
        class="h-8 w-48 min-w-0 shadow-xs"
        inputClass="text-xs"
        placeholder="Search answers…"
        aria-label="Search answers"
        value={ansSearch}
        onValueChange={setAnsSearch}
      />
      <label
        class="flex cursor-pointer select-none items-center gap-1.5 font-sans text-xs text-muted-foreground"
        title="Also search inside every folded table: the recalled facts/entities/episodes and the evidence-recall episodes"
      >
        <input
          type="checkbox"
          class="size-3.5"
          checked={ansSearchRecalled}
          onchange={(e) => setAnsSearchRecalled(e.currentTarget.checked)}
        />
        Recalled
      </label>
      <select
        class={cn(ADMIN_SELECT_SM, 'min-w-28')}
        value={ansCategory}
        onchange={(e) => setAnsCategory(e.currentTarget.value)}
        title="Filter by question type"
      >
        <option value="all">All types</option>
        {#each ansCategoryOptions as c (c)}
          <option value={c}>{c}</option>
        {/each}
      </select>
      <select
        class={cn(ADMIN_SELECT_SM, 'min-w-32')}
        value={ansDifficulty}
        onchange={(e) => setAnsDifficulty(e.currentTarget.value)}
        title="Filter by difficulty"
      >
        <option value="all">All difficulties</option>
        <option value="medium">medium</option>
        <option value="hard">hard</option>
        <option value="very_hard">very hard</option>
        <option value="unspecified">unspecified</option>
      </select>
      {#if cfg.showRecallColumn}
        <select
          class={cn(ADMIN_SELECT_SM, 'min-w-28')}
          value={ansFlag}
          onchange={(e) => setAnsFlag(e.currentTarget.value)}
          title="Filter by judge recall-sufficiency flag"
        >
          <option value="all">All flags</option>
          <option value="sufficient">Sufficient</option>
          <option value="miss">Recall miss</option>
          <option value="unknown">Not judged</option>
        </select>
      {/if}
      <select
        class={cn(ADMIN_SELECT_SM, 'min-w-32')}
        value={ansMark}
        onchange={(e) => setAnsMark(e.currentTarget.value)}
        title="Filter by answer type (judge verdict)"
      >
        <option value="all">All answer types</option>
        <option value="pass">Pass</option>
        <option value="incorrect">Incorrect</option>
        <option value="partial">Partial</option>
        <option value="fail">Fail</option>
        <option value="abstain">Abstain</option>
        <option value="not_judged">Not judged</option>
      </select>
      {#if ansFiltered}
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
          onclick={resetAnswerFilters}
          title="Clear all filters"
        >
          Reset
        </button>
      {/if}
      <button
        type="button"
        class="grid size-8 place-items-center rounded border text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        disabled={!canExpandAllFolds}
        onclick={expandAllFolds}
        title="Expand all filtered question folds and long answer text"
        aria-label="Expand all filtered question folds and long answer text"
      >
        <UnfoldVertical size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        class="grid size-8 place-items-center rounded border text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        disabled={!canCollapseAllFolds}
        onclick={collapseAllFolds}
        title="Collapse all question folds and long answer text"
        aria-label="Collapse all question folds and long answer text"
      >
        <FoldVertical size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        class="grid size-8 place-items-center rounded border text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        disabled={!canSelectAllBank}
        onclick={() => eval_.selectAll()}
        title="Select every question in the bank"
        aria-label="Select every question in the bank"
      >
        <ListChecks size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        class="grid size-8 place-items-center rounded border text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        disabled={!canClearSelection}
        onclick={() => eval_.clearSelection()}
        title="Clear the selection"
        aria-label="Clear the selection"
      >
        <ListX size={14} aria-hidden="true" />
      </button>
      {#if cfg.canExportLocomo}
        <Button
          type="button"
          variant="outline"
          class="h-8"
          disabled={traces.exportingLocomo || eval_.savedCount === 0 || !eval_.selectedCorpus}
          onclick={() => void traces.exportLocomoResults()}
          title="Download saved memory results as a LoCoMo-compatible QA JSON file"
        >
          {#if traces.exportingLocomo}
            <LoaderCircle size={14} class="animate-spin" />
          {:else}
            <Download size={14} />
          {/if}
          LoCoMo
        </Button>
      {/if}
    </AdminFilterBar>
  </div>
  {#if showMemorySummaryBar}
    <div
      class="mb-2 flex items-center gap-x-4 overflow-x-auto rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs whitespace-nowrap"
      title="Run-level memory eval summary"
    >
      {#if showRetrievalLoopSummary}
        <span class="font-semibold uppercase tracking-wide text-muted-foreground">Retrieval loop</span>
        <span class="text-muted-foreground">
          turns/Q:
          {#each [1, 2, 3, 4] as bucket (bucket)}
            <span class="ml-2 font-mono text-foreground">{bucket}={retrievalTurnsHistogram[bucket as 1 | 2 | 3 | 4]}</span>
          {/each}
        </span>
        {#if retrievalDecompositionRate != null}
          <span class="text-muted-foreground">
            decomposition
            <span class="ml-1 font-mono text-foreground">{Math.round(retrievalDecompositionRate * 100)}%</span>
          </span>
        {/if}
      {/if}
      {#if memoryRunSummary}
        <span class="font-mono text-foreground">{memoryRunSummary}</span>
      {/if}
    </div>
  {/if}
  {#if eval_.rows.length > 0 || eval_.status === 'running'}
    <EvalResultsTable
      {eval_}
      {cfg}
      {traces}
      {legColumns}
      {showDelta}
      {showRecallCol}
      {showEvidenceCol}
      {resultsColspan}
      {resultRows}
      {sort}
      {expandedRows}
      {toggleRow}
      onOpenDetails={(row) => (detailRow = row)}
      searchTerm={ansSearch}
      {allFilteredSelected}
      {someFilteredSelected}
      filteredCount={filteredSelectableIds.length}
      onToggleSelectAllFiltered={toggleSelectAllFiltered}
      selectAllDisabled={isBusy}
      {bulkTextOpen}
      {bulkTextTick}
    />
  {/if}
  <EvalNotRunList {eval_} questions={notRunQuestions} {bankPos} />
  <EvalRowDetailDialog
    row={detailRow}
    {legColumns}
    searchTerm={ansSearch}
    {recalledTerm}
    {traces}
    onClose={() => (detailRow = null)}
  />
{/if}
