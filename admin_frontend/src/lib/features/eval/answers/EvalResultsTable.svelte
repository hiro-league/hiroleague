<!--
  Unified results table: selection, #, Question, Type, Difficulty, Ideal, optional recall flag /
  evidence / answer-type columns, per-leg answer, optional Δ, Time. Rows are rendered as a single
  flat list (sort owned by EvalAnswersPane via useEvalAnswerSort). Expanding a row reveals
  EvalResultRowDetail.
-->
<script lang="ts">
  import { ChevronRight, Flag, LoaderCircle } from '@lucide/svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import EvalAnswerTableHeaderCell from '$lib/features/eval/answers/EvalAnswerTableHeaderCell.svelte';
  import EvalHighlight from '$lib/features/eval/shared/EvalHighlight.svelte';
  import EvalResultRowDetail from '$lib/features/eval/answers/EvalResultRowDetail.svelte';
  import { EVAL_ANSWERS_TABLE_STICKY_TOP } from '$lib/features/eval/shared/eval-table-ui';
  import { fmtDateTime, fmtTime } from '$lib/features/eval/shared/eval-format';
  import {
    deltaVariant,
    difficultyMeta,
    evidenceVariant,
    legLabel,
    markLabel,
    markTitle,
    markVariant
  } from '$lib/features/eval/shared/eval-display';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalAnswerSortController } from '$lib/features/eval/state/eval-answer-sort.svelte';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import {
    recallCellLabel,
    recallLoopSaturated
  } from '$lib/features/eval/answers/eval-trajectory-controller.svelte';
  import { ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';
  import { setupStickyHeightVar } from '$lib/styling/sticky-height';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    traces: EvalTraces;
    legColumns: string[];
    showDelta: boolean;
    showRecallCol: boolean;
    showEvidenceCol: boolean;
    resultsColspan: number;
    resultRows: EvalRow[];
    sort: EvalAnswerSortController;
    expandedRows: Set<number>;
    toggleRow: (index: number) => void;
    /** Active answer-search term (row highlight). */
    searchTerm: string;
    /** Recalled-search term (fold highlight). */
    recalledTerm: string;
  }
  let {
    eval_,
    cfg,
    traces,
    legColumns,
    showDelta,
    showRecallCol,
    showEvidenceCol,
    resultsColspan,
    resultRows,
    sort,
    expandedRows,
    toggleRow,
    searchTerm,
    recalledTerm
  }: Props = $props();

  // Publish the sticky <thead> height + a representative data-row height as CSS vars so an
  // expanded row's cells can pin beneath the head, and the fold's tab strip can pin beneath the
  // pinned row. Both are measured live (ResizeObserver) so font / wrap changes stay in sync.
  let theadEl = $state<HTMLTableSectionElement | null>(null);
  let firstRowEl = $state<HTMLTableRowElement | null>(null);
  $effect(() => {
    if (!theadEl) return;
    return setupStickyHeightVar(theadEl, '--admin-eval-thead-h');
  });
  $effect(() => {
    if (!firstRowEl) return;
    return setupStickyHeightVar(firstRowEl, '--admin-eval-row-h');
  });
  // Bind ONLY the index-0 row's node into `firstRowEl` (bind:this can't take a ternary; a tiny
  // action gives us the conditional capture without duplicating the row template).
  function captureFirstRow(node: HTMLTableRowElement, gi: number) {
    if (gi === 0) firstRowEl = node;
    return {
      update(newGi: number) {
        if (newGi === 0) firstRowEl = node;
        else if (firstRowEl === node) firstRowEl = null;
      },
      destroy() {
        if (firstRowEl === node) firstRowEl = null;
      }
    };
  }
</script>

<!-- Judge recall-sufficiency flag — green = sufficient, rose = miss; nothing when not judged. -->
{#snippet recallFlag(sufficient: boolean | undefined)}
  {#if sufficient !== undefined}
    <span
      class="inline-flex {sufficient
        ? 'text-emerald-600 dark:text-emerald-400'
        : 'text-rose-600 dark:text-rose-400'}"
      title={sufficient
        ? 'Recall sufficient — the recalled facts/entities/episodes contained what was needed to answer'
        : 'Recall miss — the needed fact was not in the recalled context'}
      role="img"
      aria-label={sufficient ? 'Recall sufficient' : 'Recall insufficient'}
    >
      <Flag size={13} aria-hidden="true" />
    </span>
  {/if}
{/snippet}

<!-- No overflow wrapper on the shell: a scroll container would trap the sticky header. -->
<AdminTableShell stickyHead stickyTop={EVAL_ANSWERS_TABLE_STICKY_TOP}>
  <thead bind:this={theadEl} class={ADMIN_TABLE_HEAD}>
    <tr>
      <th class="px-3 py-2 text-center" title="Select questions to run">Run?</th>
      <th class="px-3 py-2 text-left">#</th>
      <th class="px-3 py-2 text-left">Type</th>
      <th class="px-3 py-2 text-left">Question</th>
      <th class="px-3 py-2 text-left">Ideal</th>
      {#if showRecallCol}
        <EvalAnswerTableHeaderCell
          column="recall"
          {sort}
          class="text-center"
          title="Sort by judge recall-sufficiency · loop stats when agentic retrieval ran"
        >
          <Flag size={12} aria-hidden="true" />
        </EvalAnswerTableHeaderCell>
      {/if}
      {#if showEvidenceCol}
        <EvalAnswerTableHeaderCell
          column="evidence"
          {sort}
          class="text-center"
          title="Sort by evidence recall — gold evidence episodes the recall covered (LoCoMo corpora)"
        >
          Ev
        </EvalAnswerTableHeaderCell>
      {/if}
      {#each legColumns as mode (mode)}
        {#if cfg.showAnswerTypeColumn}
          <EvalAnswerTableHeaderCell column="mark" {sort} title="Sort by answer type"
            >Answer type</EvalAnswerTableHeaderCell
          >
        {:else}
          <th class="px-3 py-2 text-left">{legLabel(mode)} answer</th>
        {/if}
      {/each}
      {#if showDelta}
        <th class="px-3 py-2 text-center" title="best graph leg vs flat">&#916;</th>
      {/if}
      <EvalAnswerTableHeaderCell column="difficulty" {sort} title="Sort by Difficulty"
        >Difficulty</EvalAnswerTableHeaderCell
      >
      <EvalAnswerTableHeaderCell column="time" {sort} class="text-right" title="Sort by eval time"
        >Time</EvalAnswerTableHeaderCell
      >
    </tr>
  </thead>
  <tbody>
    {#if resultRows.length === 0 && eval_.rows.length > 0}
      <tr>
        <td colspan={resultsColspan} class="px-3 py-3 text-center font-sans text-xs text-muted-foreground">
          No answers match the filters.
        </td>
      </tr>
    {/if}
    {#each resultRows as r, gi (r.id)}
      {@const isExpanded = expandedRows.has(r.index)}
      <tr
        use:captureFirstRow={gi}
        class="border-t align-top {eval_.isSelected(r.id) ? 'bg-primary/5' : ''}"
        class:tr-sticky={isExpanded}
      >
        <td class="px-3 py-1.5 text-center">
          <input
            type="checkbox"
            class="size-3.5"
            checked={eval_.isSelected(r.id)}
            onchange={() => eval_.toggleQuestion(r.id)}
            title="Select for run"
            aria-label="Select question for run"
          />
        </td>
        <td class="px-3 py-1.5 font-mono tabular-nums text-xs text-muted-foreground"
          >{gi + 1}/{resultRows.length}</td
        >
        <td class="px-3 py-1.5 text-xs text-muted-foreground">{r.category || '—'}</td>
        <td class="px-3 py-1.5">
          <button
            type="button"
            class="flex w-full items-start gap-1.5 text-left hover:text-primary"
            onclick={() => toggleRow(r.index)}
            aria-expanded={isExpanded}
            title="Show details"
          >
            <ChevronRight
              size={13}
              class="mt-0.5 shrink-0 text-muted-foreground transition-transform {isExpanded ? 'rotate-90' : ''}"
              aria-hidden="true"
            />
            <span class="line-clamp-2" title={r.question}><EvalHighlight text={r.question} term={searchTerm} /></span>
          </button>
        </td>
        <td class="px-3 py-1.5 text-xs text-muted-foreground">
          <span class="line-clamp-2" title={r.gold || ''}>{#if r.gold}<EvalHighlight text={r.gold} term={searchTerm} />{:else}—{/if}</span>
        </td>
        {#if showRecallCol}
          {@const rleg = r.legs?.recall}
          <td class="px-3 py-1.5 text-center">
            <div class="flex flex-col items-center gap-1">
              {@render recallFlag(rleg?.mark ? (rleg.recall_sufficient ?? true) : undefined)}
              {#if rleg?.retrieval_loop}
                <span class="font-mono text-[10px] leading-tight text-muted-foreground" title="Searches/turns · recalled facts · reduce op">
                  {recallCellLabel(rleg)}
                </span>
                {#if recallLoopSaturated(rleg)}
                  <Badge variant="warning" class="font-mono text-[10px]" title="Hit max searches or parallel cap">cap</Badge>
                {/if}
              {:else if rleg?.recalled && rleg.recalled.length > 0}
                <span class="font-mono text-[10px] text-muted-foreground">{rleg.recalled.length}</span>
              {/if}
            </div>
          </td>
        {/if}
        {#if showEvidenceCol}
          <td class="px-3 py-1.5 text-center">
            {#if r.evidence_recall && r.evidence_recall.total > 0}
              {@const ev = r.evidence_recall}
              <Badge
                variant={evidenceVariant(ev.matched, ev.total)}
                class="font-mono tabular-nums"
                title="{ev.matched} of {ev.total} gold evidence episodes were recalled"
              >
                {ev.matched}/{ev.total}
              </Badge>
            {:else}
              <span class="text-xs text-muted-foreground">—</span>
            {/if}
          </td>
        {/if}
        {#each legColumns as mode (mode)}
          {#if cfg.showAnswerTypeColumn}
            <td class="whitespace-nowrap px-3 py-1.5">
              {#if r.legs[mode]}
                {@const leg = r.legs[mode]}
                <Badge variant={markVariant(leg.mark)} class="font-mono" title={markTitle(leg.mark)}>
                  {leg.mark ? `${leg.mark} ${markLabel(leg.mark)}` : '—'}
                </Badge>
              {:else}
                <span class="text-xs text-muted-foreground">—</span>
              {/if}
            </td>
          {:else}
            <td class="px-3 py-1.5">
              {#if r.legs[mode]}
                {@const leg = r.legs[mode]}
                <div class="flex items-start gap-1.5">
                  <Badge variant={markVariant(leg.mark)} class="mt-0.5 font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
                  <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}<EvalHighlight text={leg.answer} term={searchTerm} />{:else}— (no answer){/if}</span>
                </div>
              {:else}
                <span class="text-xs text-muted-foreground">—</span>
              {/if}
            </td>
          {/if}
        {/each}
        {#if showDelta}
          <td class="px-3 py-1.5 text-center">
            <Badge variant={deltaVariant(r.delta)} class="font-mono">{r.delta}</Badge>
          </td>
        {/if}
        <td class="px-3 py-1.5">
          {#if difficultyMeta(r.difficulty)}
            {@const dm = difficultyMeta(r.difficulty)}
            <span class="inline-block rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide {dm?.cls}">
              {dm?.label}
            </span>
          {:else}
            <span class="text-xs text-muted-foreground">—</span>
          {/if}
        </td>
        <td
          class="whitespace-nowrap px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground"
          title={fmtDateTime(r.answered_at)}
        >{fmtTime(r.answered_at)}</td>
      </tr>
      <!-- Fold: per-leg judge verdict + recalled facts (expanded). -->
      <tr class="border-t bg-muted/10" hidden={!isExpanded}>
        <td colspan={resultsColspan} class="px-3 py-3">
          <EvalResultRowDetail {r} {legColumns} {searchTerm} {recalledTerm} {traces} />
        </td>
      </tr>
    {/each}
    {#if eval_.status === 'running' && eval_.totalQuestions > eval_.rows.length}
      <tr class="border-t bg-muted/10">
        <td colspan={resultsColspan} class="px-3 py-2 text-center font-sans text-xs text-muted-foreground">
          <LoaderCircle size={12} class="mr-1 inline animate-spin" aria-hidden="true" />
          {eval_.rows.length} / {eval_.totalQuestions} done &middot; waiting for next&hellip;
        </td>
      </tr>
    {/if}
  </tbody>
</AdminTableShell>

<style>
  /* When a row's fold is open, pin the question row's cells beneath the sticky <thead> so the
     question stays in view while the user scrolls through the fold. `--admin-table-sticky-top`
     is set by AdminTableShell (page-pinned thead origin); `--admin-eval-thead-h` is published
     by setupStickyHeightVar from the thead itself. */
  .tr-sticky :global(td) {
    position: sticky;
    top: calc(var(--admin-table-sticky-top, 4rem) + var(--admin-eval-thead-h, 36px));
    z-index: 4;
    background: var(--background);
  }
</style>
