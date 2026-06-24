<!--
  Unified results table: selection, #, Question, Type, Difficulty, Ideal, optional recall flag /
  evidence / answer-type columns, per-leg answer, optional Δ, Time. Rows are rendered as a single
  flat list (sort owned by EvalAnswersPane via useTableSort). Expanding a row reveals
  EvalResultRowDetail.
-->
<script lang="ts">
  import { ChevronRight, CircleSlash, Flag, LoaderCircle } from '@lucide/svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import type { TableSortController } from '$lib/components/page/table/use-table-sort.svelte';
  import Highlight from '$lib/search/Highlight.svelte';
  import EvalResultRowDetail from '$lib/features/eval/answers/EvalResultRowDetail.svelte';
  import { EVAL_ANSWERS_TABLE_STICKY_TOP } from '$lib/features/eval/shared/eval-table-ui';
  import { fmtDateTime, fmtTime } from '$lib/features/eval/shared/eval-format';
  import {
    deltaVariant,
    difficultyMeta,
    evidenceVariant,
    isCorrectAbstention,
    legLabel,
    markGlyph,
    markLabel,
    markTitle,
    markVariant
  } from '$lib/features/eval/shared/eval-display';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { AnsSortKey } from '$lib/features/eval/shared/eval-derive';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import {
    recallCellLabel,
    recallLoopSaturated
  } from '$lib/features/eval/answers/eval-trajectory-controller.svelte';
  import { ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';

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
    sort: TableSortController<Exclude<AnsSortKey, 'none'>>;
    expandedRows: Set<number>;
    toggleRow: (index: number) => void;
    /** Open the giant detail dialog for a row (from the answer-type / answer cell). */
    onOpenDetails: (r: EvalRow) => void;
    /** Active answer-search term (row highlight). */
    searchTerm: string;
    /** Filtered select-all header checkbox state. */
    allFilteredSelected: boolean;
    someFilteredSelected: boolean;
    filteredCount: number;
    onToggleSelectAllFiltered: () => void;
    selectAllDisabled: boolean;
    bulkTextOpen: boolean;
    bulkTextTick: number;
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
    onOpenDetails,
    searchTerm,
    allFilteredSelected,
    someFilteredSelected,
    filteredCount,
    onToggleSelectAllFiltered,
    selectAllDisabled,
    bulkTextOpen,
    bulkTextTick
  }: Props = $props();

  let selectAllCheckboxEl = $state<HTMLInputElement | null>(null);

  const selectAllCheckboxTooltip = $derived(
    filteredCount === 0
      ? 'No filtered questions'
      : allFilteredSelected
        ? 'Deselect all filtered questions'
        : 'Select all filtered questions'
  );

  $effect(() => {
    if (selectAllCheckboxEl) {
      selectAllCheckboxEl.indeterminate = someFilteredSelected;
    }
  });
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
  <thead class={ADMIN_TABLE_HEAD}>
    <tr>
      <th class="w-10 px-3 py-2 text-center">
        <input
          bind:this={selectAllCheckboxEl}
          type="checkbox"
          class="size-3.5"
          aria-label={selectAllCheckboxTooltip}
          title={selectAllCheckboxTooltip}
          disabled={selectAllDisabled || filteredCount === 0}
          checked={allFilteredSelected}
          onchange={onToggleSelectAllFiltered}
        />
      </th>
      <th class="px-3 py-2 text-left">#</th>
      <th class="px-3 py-2 text-left">Type</th>
      <th class="px-3 py-2 text-left">Question</th>
      {#if showRecallCol}
        <AdminTableHeaderCell
          column="recall"
          {sort}
          class="text-center"
          title="Sort by judge recall-sufficiency · loop stats when agentic retrieval ran"
        >
          <Flag size={12} aria-hidden="true" />
        </AdminTableHeaderCell>
      {/if}
      {#if showEvidenceCol}
        <AdminTableHeaderCell
          column="evidence"
          {sort}
          class="text-center"
          title="Sort by evidence recall — gold evidence episodes the recall covered (LoCoMo corpora)"
        >
          Ev
        </AdminTableHeaderCell>
      {/if}
      {#each legColumns as mode (mode)}
        {#if cfg.showAnswerTypeColumn}
          <AdminTableHeaderCell column="mark" {sort} title="Sort by answer type"
            >Answer type</AdminTableHeaderCell
          >
        {:else}
          <th class="px-3 py-2 text-left">{legLabel(mode)} answer</th>
        {/if}
      {/each}
      {#if showDelta}
        <th class="px-3 py-2 text-center" title="best graph leg vs flat">&#916;</th>
      {/if}
      <AdminTableHeaderCell column="difficulty" {sort} title="Sort by Difficulty"
        >Difficulty</AdminTableHeaderCell
      >
      <AdminTableHeaderCell column="time" {sort} class="text-right" title="Sort by eval time"
        >Time</AdminTableHeaderCell
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
      <tr class="border-t align-top {eval_.isSelected(r.id) ? 'bg-primary/5' : ''}">
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
            <span class="line-clamp-2" title={r.question}><Highlight text={r.question} query={searchTerm} /></span>
          </button>
        </td>
        {#if showRecallCol}
          {@const rleg = r.legs?.recall}
          <td class="whitespace-nowrap px-3 py-1.5 text-center">
            <div class="flex flex-col items-center gap-1">
              <div class="flex items-center justify-center gap-1">
                {@render recallFlag(rleg?.mark ? (rleg.recall_sufficient ?? true) : undefined)}
                {#if rleg?.retrieval_loop && recallLoopSaturated(rleg)}
                  <Badge variant="warning" class="font-mono text-[10px]" title="Hit max searches or parallel cap">cap</Badge>
                {/if}
              </div>
              {#if rleg?.retrieval_loop}
                <span class="font-mono text-[10px] leading-tight text-muted-foreground" title="Searches/turns · recalled facts">
                  {recallCellLabel(rleg)}
                </span>
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
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded hover:bg-primary/5"
                  onclick={() => onOpenDetails(r)}
                  title="Open full diagnostic detail"
                >
                  <Badge variant={markVariant(leg.mark, r.is_negative_control)} class="font-mono" title={markTitle(leg.mark, r.is_negative_control)}>
                    {leg.mark ? `${markGlyph(leg.mark, r.is_negative_control)} ${markLabel(leg.mark, r.is_negative_control)}` : '—'}
                  </Badge>
                  {#if isCorrectAbstention(leg.mark, r.is_negative_control)}
                    <span class="inline-flex text-muted-foreground" title="Abstained — declined on this negative-control question (counts as a pass)"><CircleSlash class="size-3.5" aria-label="Abstained" /></span>
                  {/if}
                </button>
              {:else}
                <span class="text-xs text-muted-foreground">—</span>
              {/if}
            </td>
          {:else}
            <td class="px-3 py-1.5">
              {#if r.legs[mode]}
                {@const leg = r.legs[mode]}
                <button
                  type="button"
                  class="flex w-full items-start gap-1.5 rounded text-left hover:bg-primary/5"
                  onclick={() => onOpenDetails(r)}
                  title="Open full diagnostic detail"
                >
                  <Badge variant={markVariant(leg.mark, r.is_negative_control)} class="mt-0.5 font-mono" title={markTitle(leg.mark, r.is_negative_control)}>{markGlyph(leg.mark, r.is_negative_control) || '—'}</Badge>
                  {#if isCorrectAbstention(leg.mark, r.is_negative_control)}
                    <span class="mt-0.5 inline-flex text-muted-foreground" title="Abstained — declined on this negative-control question (counts as a pass)"><CircleSlash class="size-3.5" aria-label="Abstained" /></span>
                  {/if}
                  <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}<Highlight text={leg.answer} query={searchTerm} />{:else}— (no answer){/if}</span>
                </button>
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
      <!-- Slim fold: ideal answer + per-leg stats/actions + "Open details" (expanded). -->
      <tr class="border-y border-border/70 bg-muted/55" hidden={!isExpanded}>
        <td class="bg-muted/55 px-3 py-3"></td>
        <td colspan={resultsColspan - 1} class="bg-muted/55 px-3 py-3">
          <EvalResultRowDetail
            {r}
            {legColumns}
            {searchTerm}
            {traces}
            {bulkTextOpen}
            {bulkTextTick}
            onOpenDetails={() => onOpenDetails(r)}
          />
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
