<!--
  Questions/Answers pane — a sticky toolbar (run-selection + search/filters + group expand-all +
  LoCoMo export) over the grouped results table (EvalResultsTable) and the still-unanswered bank
  questions (EvalNotRunList). Owns ALL answer-view state: filters, intra-group sort, row + group
  expansion, and the sticky controls-bar height var the table's sticky thead pins beneath.
-->
<script lang="ts">
  import { ChevronsDownUp, ChevronsUpDown, Download, LoaderCircle, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { setupStickyHeightVar } from '$lib/styling/sticky-height';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import EvalResultsTable from '$lib/features/eval/answers/EvalResultsTable.svelte';
  import EvalNotRunList from '$lib/features/eval/answers/EvalNotRunList.svelte';
  import { pct } from '$lib/features/eval/shared/eval-format';
  import {
    rowHaystack,
    rowMatchesFlag,
    rowMatchesMark,
    type AnsFlag,
    type AnsMark,
    type AnsSortKey
  } from '$lib/features/eval/shared/eval-derive';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    traces: EvalTraces;
  }
  let { eval_, cfg, traces }: Props = $props();

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

  // --- Filters (search + type + difficulty + recall flag + answer type) ---------------------
  let ansSearch = $state('');
  let ansSearchRecalled = $state(false);
  let ansCategory = $state<string>('all');
  type QDifficulty = 'all' | 'medium' | 'hard' | 'very_hard' | 'unspecified';
  let ansDifficulty = $state<QDifficulty>('all');
  let ansFlag = $state<AnsFlag>('all');
  let ansMark = $state<AnsMark>('all');
  // Highlight inside the recalled tables only when recalled search is enabled.
  const recalledTerm = $derived(ansSearchRecalled ? ansSearch : '');
  const ansFiltered = $derived(
    ansSearch.trim() !== '' ||
      ansCategory !== 'all' ||
      ansDifficulty !== 'all' ||
      ansFlag !== 'all' ||
      ansMark !== 'all'
  );
  function resetAnswerFilters() {
    ansSearch = '';
    ansSearchRecalled = false;
    ansCategory = 'all';
    ansDifficulty = 'all';
    ansFlag = 'all';
    ansMark = 'all';
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

  // --- Intra-group sort (within each category group) ----------------------------------------
  let ansSortKey = $state<AnsSortKey>('none');
  let ansSortDir = $state<'asc' | 'desc'>('asc');
  function cycleAnsSort(key: Exclude<AnsSortKey, 'none'>) {
    if (ansSortKey !== key) {
      ansSortKey = key;
      ansSortDir = 'asc';
    } else if (ansSortDir === 'asc') {
      ansSortDir = 'desc';
    } else {
      ansSortKey = 'none';
      ansSortDir = 'asc';
    }
  }

  // --- Results grouped by type (category) ---------------------------------------------------
  const resultGroups = $derived.by<[string, EvalRow[]][]>(() => {
    const map = new Map<string, EvalRow[]>();
    for (const r of filteredAnswerRows) {
      const cat = r.category || '—';
      const arr = map.get(cat) ?? [];
      arr.push(r);
      map.set(cat, arr);
    }
    for (const arr of map.values()) arr.sort((a, b) => a.index - b.index);
    return [...map.entries()];
  });
  let collapsedResultGroups = $state<Set<string>>(new Set());
  function toggleResultGroup(cat: string) {
    const next = new Set(collapsedResultGroups);
    if (next.has(cat)) next.delete(cat);
    else next.add(cat);
    collapsedResultGroups = next;
  }
  function expandAllResultGroups() {
    collapsedResultGroups = new Set();
  }
  function collapseAllResultGroups() {
    collapsedResultGroups = new Set(resultGroups.map(([cat]) => cat));
  }

  // --- Table column shape (legs + optional columns) -----------------------------------------
  const legColumns = $derived(eval_.runModes);
  const showDelta = $derived(cfg.showDelta);
  const showRecallCol = $derived(cfg.showRecallColumn);
  const showEvidenceCol = $derived(cfg.showEvidenceColumn);
  // Base 6 = select + #, Question, Type, Difficulty, Ideal; + legs + optional columns + Time.
  const resultsColspan = $derived(
    6 +
      legColumns.length +
      (showDelta ? 1 : 0) +
      (showRecallCol ? 1 : 0) +
      (showEvidenceCol ? 1 : 0) +
      (cfg.showAnswerTypeColumn ? 1 : 0) +
      1
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
  <!-- Sticky controls: run-selection + search/filters + group expand-all + LoCoMo export. -->
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
    <div class="relative">
      <input
        class="h-7 w-48 rounded-md border bg-background pl-2 pr-7 font-sans text-xs"
        placeholder="Search answers…"
        bind:value={ansSearch}
        title="Searches the answer surface — question, ideal, answers, judge reason/evidence. Enable “Recalled” to also search every folded table: recalled facts/entities/episodes and the evidence-recall episodes."
      />
      {#if ansSearch.trim()}
        <button
          type="button"
          class="absolute inset-y-0 right-1.5 my-auto flex size-4 items-center justify-center rounded text-muted-foreground hover:text-foreground"
          onclick={() => (ansSearch = '')}
          title="Clear search"
          aria-label="Clear search"
        >
          <X size={12} aria-hidden="true" />
        </button>
      {/if}
    </div>
    <label
      class="flex cursor-pointer select-none items-center gap-1.5 font-sans text-xs text-muted-foreground"
      title="Also search inside every folded table: the recalled facts/entities/episodes and the evidence-recall episodes"
    >
      <input type="checkbox" class="size-3.5" bind:checked={ansSearchRecalled} />
      Recalled
    </label>
    <select
      class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
      bind:value={ansCategory}
      title="Filter by question type"
    >
      <option value="all">All types</option>
      {#each ansCategoryOptions as c (c)}
        <option value={c}>{c}</option>
      {/each}
    </select>
    <select
      class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
      bind:value={ansDifficulty}
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
        class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
        bind:value={ansFlag}
        title="Filter by judge recall-sufficiency flag"
      >
        <option value="all">All flags</option>
        <option value="sufficient">Sufficient</option>
        <option value="miss">Recall miss</option>
        <option value="unknown">Not judged</option>
      </select>
    {/if}
    <select
      class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
      bind:value={ansMark}
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
    {#if resultGroups.length > 0}
      <button
        type="button"
        class="rounded border p-1 hover:bg-muted"
        onclick={expandAllResultGroups}
        title="Expand all groups"
        aria-label="Expand all groups"
      >
        <ChevronsUpDown size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        class="rounded border p-1 hover:bg-muted"
        onclick={collapseAllResultGroups}
        title="Collapse all groups"
        aria-label="Collapse all groups"
      >
        <ChevronsDownUp size={14} aria-hidden="true" />
      </button>
    {/if}
    {#if cfg.canExportLocomo}
      <Button
        type="button"
        variant="outline"
        class="h-7"
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
  </div>
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
      {resultGroups}
      {collapsedResultGroups}
      {toggleResultGroup}
      {ansSortKey}
      {ansSortDir}
      {cycleAnsSort}
      {expandedRows}
      {toggleRow}
      searchTerm={ansSearch}
      {recalledTerm}
    />
  {/if}
  <EvalNotRunList {eval_} questions={notRunQuestions} {bankPos} />
{/if}
