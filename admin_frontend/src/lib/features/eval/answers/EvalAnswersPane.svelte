<!--
  Questions/Answers pane — a sticky toolbar (run-selection + search/filters + LoCoMo export) over
  the flat results table (EvalResultsTable) and the still-unanswered bank questions
  (EvalNotRunList). Owns ALL answer-view state: filters, sort, row expansion, and the sticky
  controls-bar height var the table's sticky thead pins beneath.
-->
<script lang="ts">
  import { Download, LoaderCircle, X } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { setupStickyHeightVar } from '$lib/styling/sticky-height';
  import { ADMIN_SELECT_SM } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import EvalResultsTable from '$lib/features/eval/answers/EvalResultsTable.svelte';
  import EvalNotRunList from '$lib/features/eval/answers/EvalNotRunList.svelte';
  import {
    EVAL_TOOLBAR_SEARCH,
    EVAL_TOOLBAR_SEARCH_INPUT
  } from '$lib/features/eval/shared/eval-table-ui';
  import { pct } from '$lib/features/eval/shared/eval-format';
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
    type AnsMark
  } from '$lib/features/eval/shared/eval-derive';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import { useEvalAnswerSort } from '$lib/features/eval/state/eval-answer-sort.svelte';
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

  const sort = useEvalAnswerSort();
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Results-card header summary: the gate verdict once complete, otherwise live progress.
  const resultsSummary = $derived.by(() => {
    if (eval_.summary) {
      if (eval_.summary.track === 'memory')
        return `recalled ${eval_.summary.recalled_for ?? 0}/${eval_.summary.total_questions} · ${eval_.summary.elapsed_ms}ms`;
      const g = eval_.summary.gate;
      const label = g === 'proceed' ? '✅ PROCEED' : g === 'pivot' ? '❌ PIVOT' : 'Done';
      return `${label} · ${eval_.summary.elapsed_ms}ms`;
    }
    if (eval_.rows.length > 0) return `${eval_.rows.length}/${eval_.totalQuestions}`;
    return '';
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
  const ansCategoryOptions = $derived.by(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const r of eval_.rows) {
      const c = r.category || '';
      if (c && !seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
    return out;
  });
  const filteredAnswerRows = $derived.by(() => {
    const term = ansSearch.trim().toLowerCase();
    return eval_.rows.filter((r) => {
      if (ansCategory !== 'all' && (r.category || '') !== ansCategory) return false;
      if (ansDifficulty !== 'all' && (r.difficulty || 'unspecified') !== ansDifficulty) return false;
      if (cfg.showRecallColumn && !rowMatchesFlag(r, ansFlag)) return false;
      if (!rowMatchesMark(r, ansMark)) return false;
      if (term && !rowHaystack(r, ansSearchRecalled).includes(term)) return false;
      return true;
    });
  });

  // --- Flat results list (sorted) -----------------------------------------------------------
  const resultRows = $derived.by<EvalRow[]>(() => {
    const sorted = [...filteredAnswerRows].sort((a, b) => a.index - b.index);
    return sortGroupRows(sorted, sort.sortKey, sort.sortDir);
  });

  const retrievalTurnsHistogram = $derived(turnsPerQuestionHistogram(eval_.rows));
  const retrievalDecompositionRate = $derived(decompositionRate(eval_.rows));
  const showRetrievalLoopSummary = $derived(
    cfg.track === 'memory' && eval_.rows.some((row) => row.legs.recall?.retrieval_loop)
  );

  // --- Table column shape (legs + optional columns) -----------------------------------------
  const legColumns = $derived(eval_.runModes);
  const showDelta = $derived(cfg.showDelta);
  const showRecallCol = $derived(cfg.showRecallColumn);
  const showEvidenceCol = $derived(cfg.showEvidenceColumn);
  // Base 5 = select + #, Type, Question, Ideal; + legs (1/leg: answer-type for memory, answer for
  // knowledge) + optional recall/evidence/Δ columns + Difficulty + Time.
  const resultsColspan = $derived(
    5 +
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
    const term = ansSearch.trim().toLowerCase();
    return eval_.questions.filter((q) => {
      if (answeredIds.has(q.id)) return false;
      if (ansCategory !== 'all' && (q.category || '') !== ansCategory) return false;
      if (ansDifficulty !== 'all' && (q.difficulty || 'unspecified') !== ansDifficulty) return false;
      if (term && !`${q.question} ${q.id} ${q.category} ${q.subcategory ?? ''}`.toLowerCase().includes(term))
        return false;
      return true;
    });
  });
</script>

{#if eval_.questions.length === 0}
  <InlineEmptyState message="No questions loaded — pick a corpus on the Execute tab." />
{:else}
  <!-- Sticky controls: run-selection + search/filters + LoCoMo export. -->
  <div
    bind:this={aControlsEl}
    class="sticky z-10 flex flex-wrap items-center gap-2 bg-background py-2"
    style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px));"
  >
    <span class="mr-auto font-sans text-xs text-muted-foreground">
      <span class="font-medium text-foreground">{eval_.selectedCount}</span>/{eval_.questions
        .length} selected{#if resultsSummary} · {resultsSummary}{/if}{#if ansFiltered}
        · {filteredAnswerRows.length}/{eval_.rows.length} shown{/if}
    </span>
    {#if eval_.questions.length > 0}
      <button
        type="button"
        class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
        onclick={() => eval_.selectAll()}
        disabled={isBusy}
        title="Select every question in the bank"
      >
        Select all
      </button>
      {#if eval_.selectedCount > 0}
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
          onclick={() => eval_.clearSelection()}
          disabled={isBusy}
          title="Clear the selection"
        >
          Clear ({eval_.selectedCount})
        </button>
      {/if}
    {/if}
    <AdminFilterBar class="ml-auto items-center gap-2">
      <label
        class={EVAL_TOOLBAR_SEARCH}
        title="Searches the answer surface — question, ideal, answers, judge reason/evidence. Enable “Recalled” to also search every folded table: recalled facts/entities/episodes and the evidence-recall episodes."
      >
        <input
          class={EVAL_TOOLBAR_SEARCH_INPUT}
          placeholder="Search answers…"
          value={ansSearch}
          oninput={(e) => setAnsSearch(e.currentTarget.value)}
        />
        {#if ansSearch.trim()}
          <button
            type="button"
            class="grid size-5 place-items-center rounded text-muted-foreground hover:text-foreground"
            onclick={() => setAnsSearch('')}
            title="Clear search"
            aria-label="Clear search"
          >
            <X size={12} aria-hidden="true" />
          </button>
        {/if}
      </label>
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
          Export to LoCoMo
        </Button>
      {/if}
    </AdminFilterBar>
  </div>
  {#if showRetrievalLoopSummary}
    <div
      class="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs"
      title="Run-level agentic retrieval diagnostics"
    >
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
      searchTerm={ansSearch}
      {recalledTerm}
    />
  {/if}
  <EvalNotRunList {eval_} questions={notRunQuestions} {bankPos} />
{/if}
