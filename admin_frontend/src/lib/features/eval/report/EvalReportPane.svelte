<!--
  Report pane — aggregate breakdown for the selected corpus (and, on tracks with benchmarks, a
  benchmark overview: totals by category/difficulty + a per-corpus summary table that drills into
  each corpus's detail). A header line carries the run summary + the Clear-results action (which
  wipes the report + answer details). Rendered directly (no collapsible card).
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { ChevronDown, ChevronRight, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { fmtCost, pct } from '$lib/features/eval/shared/eval-format';
  import { orderedDifficulty } from '$lib/features/eval/shared/eval-display';
  import EvalBreakdownTable from '$lib/features/eval/report/EvalBreakdownTable.svelte';
  import {
    readEvalReportSections,
    writeEvalReportSections,
    type EvalReportSection
  } from '$lib/features/eval/report/eval-report-prefs';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import { ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    /** Open the Clear-results flow (memory: confirm dialog; knowledge: immediate in-view reset). */
    onRequestClear: () => void;
    /** Select corpus — may prompt on knowledge track; resolves when applied or cancelled. */
    onSelectCorpus: (id: string) => Promise<boolean>;
  }
  let { eval_, cfg, onRequestClear, onSelectCorpus }: Props = $props();

  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Report-card header summary: overall correct count + correct% / score% across all legs
  // (graded runs only). For the multi-leg knowledge track this uses the best leg's correct count.
  const reportSummary = $derived.by(() => {
    const s = eval_.summary;
    if (!s || s.judged === false || !s.passing) return '';
    const total = s.total_questions || 0;
    const best = Math.max(0, ...Object.values(s.passing));
    const bestScore = s.scoring ? Math.max(0, ...Object.values(s.scoring)) : best;
    return `correct ${best}/${total} · ${pct(best, total)} · score ${pct(bestScore, total)}`;
  });

  // Per-report-section expand/collapse — persisted so the tab reopens the way the user left it
  // (the pane re-mounts on every sub-tab switch and rebuilds these tables on every corpus change).
  let sections = $state(readEvalReportSections());
  $effect(() => writeEvalReportSections(sections));
  const toggleSection = (id: EvalReportSection) => (sections[id] = !sections[id]);

  // Scroll target for the per-corpus detail.
  let reportDetailEl = $state<HTMLElement | null>(null);
  async function selectCorpusAndScroll(id: string) {
    const ok = await onSelectCorpus(id);
    if (!ok) return;
    await tick(); // let the detail render for the newly selected corpus before scrolling
    reportDetailEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
</script>

{#if cfg.hasBenchmarks}
  <!-- Benchmark overview — totals by category/difficulty + one summary row per corpus, for the
       benchmark selected on the Execute tab. Clicking a corpus row drills into its detail below. -->
  {#if eval_.benchmarkResultsLoading && !eval_.benchmarkResults}
    <InlineLoading label="Loading benchmark results…" />
  {/if}
  {#if eval_.benchmarkResultsError}
    <InlineDestructiveAlert message={eval_.benchmarkResultsError} class="mt-2" />
  {:else if eval_.benchmarkResults}
    {@const bench = eval_.benchmarkResults}
    {#if bench.total}
      {#if bench.total.by_category && Object.keys(bench.total.by_category).length > 0}
        <EvalBreakdownTable
          title={`${bench.benchmark.label} · Total Results by Category`}
          bc={bench.total.by_category}
          cols={bench.total.modes}
          header="Category"
          collapsed={sections.benchCategory}
          onToggleCollapsed={() => toggleSection('benchCategory')}
        />
      {/if}
      {#if bench.total.by_difficulty && Object.keys(bench.total.by_difficulty).length > 0}
        <EvalBreakdownTable
          title={`${bench.benchmark.label} · Total Results by Difficulty`}
          bc={orderedDifficulty(bench.total.by_difficulty)}
          cols={bench.total.modes}
          header="Difficulty"
          collapsed={sections.benchDifficulty}
          onToggleCollapsed={() => toggleSection('benchDifficulty')}
        />
      {/if}
    {/if}
    <!-- Per-corpus summary table (collapsible) — click a row to drill into its detail. -->
    <button
      type="button"
      class="mt-2 flex items-center gap-1.5 font-sans"
      onclick={() => toggleSection('benchByCorpus')}
      aria-expanded={!sections.benchByCorpus}
    >
      {#if sections.benchByCorpus}
        <ChevronRight size={15} aria-hidden="true" />
      {:else}
        <ChevronDown size={15} aria-hidden="true" />
      {/if}
      <span class="text-sm font-semibold">{bench.benchmark.label} · By corpus</span>
    </button>
    {#if !sections.benchByCorpus}
      <AdminTableShell class="mt-1">
        <thead class={ADMIN_TABLE_HEAD}>
          <tr>
            <th class="px-3 py-2 text-left">Corpus</th>
            <th class="px-3 py-2 text-right">Answered</th>
            <th class="px-3 py-2 text-right">Pass</th>
            <th class="px-3 py-2 text-right">Score</th>
            <th class="px-3 py-2 text-right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {#each bench.corpuses as c (c.corpus_id)}
            {@const ans = c.answered}
            {@const pass = c.summary?.passing?.recall ?? 0}
            {@const score = c.summary?.scoring?.recall ?? 0}
            <tr
              class="cursor-pointer border-t hover:bg-muted/40 {c.corpus_id === eval_.selectedCorpusId
                ? 'bg-primary/5'
                : ''}"
              onclick={() => void selectCorpusAndScroll(c.corpus_id)}
            >
              <td class="px-3 py-1.5">{c.label}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{ans}/{c.bank_questions}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{ans ? pct(pass, ans) : '—'}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{ans ? pct(score, ans) : '—'}</td>
              <td class="px-3 py-1.5 text-right tabular-nums"
                >{c.has_results ? fmtCost(c.summary?.total_cost_usd) : '—'}</td
              >
            </tr>
          {/each}
        </tbody>
        {#if bench.total}
          {@const tans = bench.total.total_questions}
          {@const tbank = bench.corpuses.reduce((s, c) => s + c.bank_questions, 0)}
          {@const tpass = bench.total.passing?.recall ?? 0}
          {@const tscore = bench.total.scoring?.recall ?? 0}
          <tfoot>
            <tr class="border-t-2 font-semibold">
              <td class="px-3 py-1.5">TOTAL</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{tans}/{tbank}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{tans ? pct(tpass, tans) : '—'}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{tans ? pct(tscore, tans) : '—'}</td>
              <td class="px-3 py-1.5 text-right tabular-nums">{fmtCost(bench.total.total_cost_usd)}</td>
            </tr>
          </tfoot>
        {/if}
      </AdminTableShell>
      <p class="mt-1 font-sans text-[11px] text-muted-foreground">
        Click a corpus to load its detailed breakdown below.
      </p>
    {/if}
  {/if}
  <hr class="my-4 border-muted" />
{/if}

<!-- Per-corpus detail — the selected corpus's breakdown (chosen on Execute or by clicking a row
     above; always within the current benchmark). -->
<div bind:this={reportDetailEl}>
  {#if !eval_.summary}
    <InlineEmptyState
      message={cfg.hasBenchmarks
        ? 'Select a corpus above to load its detailed breakdown.'
        : 'No report yet — run an eval to see the aggregate breakdown here.'}
    />
  {:else}
    <div class="flex flex-wrap items-center gap-2">
      <span class="mr-auto font-sans text-xs text-muted-foreground">
        {#if cfg.hasBenchmarks && eval_.selectedCorpus}<span class="font-medium text-foreground"
            >{eval_.selectedCorpus.label ?? eval_.selectedCorpus.name}</span
          > · {/if}{reportSummary}
      </span>
      {#if eval_.rows.length > 0 || eval_.summary || eval_.failureMessage || (cfg.persistsResults && eval_.savedCount > 0)}
        <Button
          variant="outline"
          class="h-7"
          disabled={isBusy}
          onclick={onRequestClear}
          title={cfg.persistsResults
            ? 'Delete this corpus’s saved results from disk — wipes the report + answer details (ingested memory is kept)'
            : "Clear this run's report + answer details"}
        >
          <Trash2 size={14} /> {cfg.clearLabel}
        </Button>
      {/if}
    </div>
    {#if eval_.summary.by_category && Object.keys(eval_.summary.by_category).length > 0}
      <EvalBreakdownTable
        title="Results by category"
        bc={eval_.summary.by_category}
        cols={eval_.summary.modes}
        header="Category"
        collapsed={sections.detailCategory}
        onToggleCollapsed={() => toggleSection('detailCategory')}
      />
    {/if}
    {#if eval_.summary.by_difficulty && Object.keys(eval_.summary.by_difficulty).length > 0}
      <EvalBreakdownTable
        title="Results by difficulty"
        bc={orderedDifficulty(eval_.summary.by_difficulty)}
        cols={eval_.summary.modes}
        header="Difficulty"
        collapsed={sections.detailDifficulty}
        onToggleCollapsed={() => toggleSection('detailDifficulty')}
      />
    {/if}
  {/if}
</div>
