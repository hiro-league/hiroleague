<!--
  Unified results table: selection, #, Question, Type, Difficulty, Ideal, optional recall flag /
  evidence / answer-type columns, per-leg answer, optional Δ, Time. Rows are grouped by type
  (category); each group is collapsible. Expanding a row reveals EvalResultRowDetail. Sort state
  is owned by EvalAnswersPane (useEvalAnswerSort) and passed in.
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
  import { sortGroupRows } from '$lib/features/eval/shared/eval-derive';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalAnswerSortController } from '$lib/features/eval/state/eval-answer-sort.svelte';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
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
    resultGroups: [string, EvalRow[]][];
    collapsedResultGroups: Set<string>;
    toggleResultGroup: (cat: string) => void;
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
    resultGroups,
    collapsedResultGroups,
    toggleResultGroup,
    sort,
    expandedRows,
    toggleRow,
    searchTerm,
    recalledTerm
  }: Props = $props();
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
      <th class="px-3 py-2 text-center" title="Select questions to run">Run?</th>
      <th class="px-3 py-2 text-left">#</th>
      <th class="px-3 py-2 text-left">Question</th>
      <th class="px-3 py-2 text-left">Type</th>
      <EvalAnswerTableHeaderCell column="difficulty" {sort} title="Sort by Difficulty"
        >Difficulty</EvalAnswerTableHeaderCell
      >
      <th class="px-3 py-2 text-left">Ideal</th>
      {#if showRecallCol}
        <EvalAnswerTableHeaderCell
          column="recall"
          {sort}
          class="text-center"
          title="Sort by judge recall-sufficiency"
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
        {/if}
        <th class="px-3 py-2 text-left">{legLabel(mode)} answer</th>
      {/each}
      {#if showDelta}
        <th class="px-3 py-2 text-center" title="best graph leg vs flat">&#916;</th>
      {/if}
      <EvalAnswerTableHeaderCell column="time" {sort} class="text-right" title="Sort by eval time"
        >Time</EvalAnswerTableHeaderCell
      >
    </tr>
  </thead>
  <tbody>
    {#if resultGroups.length === 0 && eval_.rows.length > 0}
      <tr>
        <td colspan={resultsColspan} class="px-3 py-3 text-center font-sans text-xs text-muted-foreground">
          No answers match the filters.
        </td>
      </tr>
    {/if}
    {#each resultGroups as [groupCat, groupRows] (groupCat)}
      {@const groupCollapsed = collapsedResultGroups.has(groupCat)}
      <tr class="border-t bg-muted/40">
        <td colspan={resultsColspan} class="px-3 py-1">
          <button
            type="button"
            class="flex w-full items-center gap-1.5 text-left font-sans text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
            aria-expanded={!groupCollapsed}
            onclick={() => toggleResultGroup(groupCat)}
            title={groupCollapsed ? 'Expand group' : 'Collapse group'}
          >
            <ChevronRight
              size={13}
              class="shrink-0 transition-transform {groupCollapsed ? '' : 'rotate-90'}"
              aria-hidden="true"
            />
            {groupCat}
            <span class="font-normal normal-case">({groupRows.length})</span>
          </button>
        </td>
      </tr>
      {#if !groupCollapsed}
        {@const sortedRows = sortGroupRows(groupRows, sort.sortKey, sort.sortDir)}
        {#each sortedRows as r, gi (r.id)}
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
              >{gi + 1}/{sortedRows.length}</td
            >
            <td class="px-3 py-1.5">
              <button
                type="button"
                class="flex w-full items-start gap-1.5 text-left hover:text-primary"
                onclick={() => toggleRow(r.index)}
                aria-expanded={expandedRows.has(r.index)}
                title="Show details"
              >
                <ChevronRight
                  size={13}
                  class="mt-0.5 shrink-0 text-muted-foreground transition-transform {expandedRows.has(r.index) ? 'rotate-90' : ''}"
                  aria-hidden="true"
                />
                <span class="line-clamp-2" title={r.question}><EvalHighlight text={r.question} term={searchTerm} /></span>
              </button>
            </td>
            <td class="px-3 py-1.5 text-xs text-muted-foreground">{r.category || '—'}</td>
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
            <td class="px-3 py-1.5 text-xs text-muted-foreground">
              <span class="line-clamp-2" title={r.gold || ''}>{#if r.gold}<EvalHighlight text={r.gold} term={searchTerm} />{:else}—{/if}</span>
            </td>
            {#if showRecallCol}
              {@const rleg = r.legs?.recall}
              <td class="px-3 py-1.5 text-center">
                {@render recallFlag(rleg?.mark ? (rleg.recall_sufficient ?? true) : undefined)}
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
              {/if}
              <td class="px-3 py-1.5">
                {#if r.legs[mode]}
                  {@const leg = r.legs[mode]}
                  {#if cfg.showAnswerTypeColumn}
                    <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}<EvalHighlight text={leg.answer} term={searchTerm} />{:else}— (no answer){/if}</span>
                  {:else}
                    <div class="flex items-start gap-1.5">
                      <Badge variant={markVariant(leg.mark)} class="mt-0.5 font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
                      <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}<EvalHighlight text={leg.answer} term={searchTerm} />{:else}— (no answer){/if}</span>
                    </div>
                  {/if}
                {:else}
                  <span class="text-xs text-muted-foreground">—</span>
                {/if}
              </td>
            {/each}
            {#if showDelta}
              <td class="px-3 py-1.5 text-center">
                <Badge variant={deltaVariant(r.delta)} class="font-mono">{r.delta}</Badge>
              </td>
            {/if}
            <td
              class="whitespace-nowrap px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground"
              title={fmtDateTime(r.answered_at)}
            >{fmtTime(r.answered_at)}</td>
          </tr>
          <!-- Fold: per-leg judge verdict + recalled facts (expanded). -->
          <tr class="border-t bg-muted/10" hidden={!expandedRows.has(r.index)}>
            <td colspan={resultsColspan} class="px-3 py-3">
              <EvalResultRowDetail {r} {legColumns} {searchTerm} {recalledTerm} {traces} />
            </td>
          </tr>
        {/each}
      {/if}
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
