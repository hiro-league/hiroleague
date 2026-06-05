<!--
  L3 prototype (Phase 5e) — Eval Batch section.

  Lives at the bottom of the Ask tab (collapsible). Three phases of UI:

    1. idle  → setup checkboxes (ingest synthetic / build graph) + Run button
    2. running → live progress table; rows append/update as
                 ``knowledge.eval.question_completed`` events arrive
    3. completed → final summary card with PROCEED/PIVOT gate verdict

  All transport plumbing lives in the controller (`knowledge-eval.svelte.ts`);
  this component is a thin view.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { ChevronRight, ExternalLink, LoaderCircle, Play, Square, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import KnowledgeAskEvalTerminal from '$lib/features/knowledge/ask/KnowledgeAskEvalTerminal.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { EvalQuestionItem } from '$lib/api/knowledge';
  import {
    createKnowledgeEvalModel,
    EVAL_ALL_LEGS,
    EVAL_LEG_LABEL,
    EVAL_MAX_SELECTED,
    type KnowledgeEvalModel
  } from '$lib/features/knowledge/state/knowledge-eval.svelte';

  interface Props {
    /** Pass-through error sink (the Ask page already owns the error display). */
    setError: (message: string | null) => void;
  }

  let { setError }: Props = $props();
  // Wrap in a closure so the controller captures the *live* reference (Svelte 5
  // ``state_referenced_locally`` rule — bare ``{ setError }`` would snapshot the
  // initial prop value at controller-construction time).
  const eval_: KnowledgeEvalModel = createKnowledgeEvalModel({
    setError: (msg) => setError(msg)
  });

  onDestroy(() => eval_.teardown());
  onMount(() => {
    // Subscribe to live events + replay the server-side run state (survives
    // navigation mid-run; consistent across the Vite/packaged origins).
    void eval_.init();
    // Load the question bank for the checklist (Adam path).
    if (eval_.corpusSource === 'adam') void eval_.loadQuestions();
  });

  // Per-row expansion (full answers). Keyed by question index; reassigned on
  // mutation so Svelte 5 tracks the Set.
  let expandedRows = $state<Set<number>>(new Set());
  function toggleRow(index: number) {
    const next = new Set(expandedRows);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    expandedRows = next;
  }

  // Collapse toggle for the Questions checklist card (header click). Body stays
  // mounted (hidden) so selection state survives a collapse.
  let questionsCollapsed = $state(false);

  // Group the question bank by category for the checklist.
  const groups = $derived.by(() => {
    const map = new Map<string, EvalQuestionItem[]>();
    for (const q of eval_.questions) {
      const arr = map.get(q.category) ?? [];
      arr.push(q);
      map.set(q.category, arr);
    }
    return [...map.entries()];
  });

  function categoryAllSelected(items: EvalQuestionItem[]): boolean {
    return items.length > 0 && items.every((q) => eval_.isSelected(q.id));
  }

  // Header summary so the collapsed card still tells the user the current state.
  const headerSummary = $derived.by(() => {
    switch (eval_.status) {
      case 'idle':
        return '';
      case 'starting':
        if (eval_.setupPhase?.phase === 'ingest_synthetic')
          return `Ingesting synthetic corpus${
            eval_.setupPhase.file_count ? ` · ${eval_.setupPhase.file_count} files` : ''
          }…`;
        if (eval_.setupPhase?.phase === 'graph_build') return 'Building graph…';
        return 'Starting…';
      case 'running':
        return `Running ${eval_.rows.length} / ${eval_.totalQuestions}`;
      case 'completed': {
        if (!eval_.summary) return 'Done';
        const g = eval_.summary.gate;
        const label = g === 'proceed' ? '✅ PROCEED' : g === 'pivot' ? '❌ PIVOT' : 'ℹ️ Done';
        return `${label} · ${eval_.summary.elapsed_ms}ms`;
      }
      case 'failed':
        return '❌ Failed';
      case 'cancelled':
        return '🛑 Cancelled';
    }
  });

  const canRun = $derived(
    eval_.status === 'idle' ||
      eval_.status === 'completed' ||
      eval_.status === 'failed' ||
      eval_.status === 'cancelled'
  );
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  /** Color the mark chip. Negative-control abstain (🛇) reads as neutral, not green. */
  function markVariant(mark: string): 'success' | 'warning' | 'destructive' | 'secondary' {
    if (mark === '✓') return 'success';
    if (mark === '◐') return 'warning';
    if (mark === '✗') return 'destructive';
    return 'secondary'; // 🛇 abstain
  }

  function deltaVariant(delta: string): 'success' | 'warning' | 'secondary' {
    if (delta.startsWith('+')) return 'success';
    if (delta.startsWith('-')) return 'warning';
    return 'secondary';
  }

  function legLabel(mode: string): string {
    return EVAL_LEG_LABEL[mode] ?? mode;
  }

  // Columns for the live table = the legs the current run used (1–3).
  const legColumns = $derived(eval_.runModes);
  // Total table column count for full-width rows (spinner / spacer):
  // ▲, #, Question, Category, <N legs>, Δ, Links.
  const tableColspan = $derived(4 + legColumns.length + 2);

</script>

<KnowledgeCollapsibleSectionCard
  title="L3 Eval Batch"
  bodyId="knowledge-ask-eval-batch"
  defaultExpanded={false}
  summary={headerSummary}
>
  <!-- Setup row — only visible/editable when idle/completed/failed.
       Disabled while a run is in flight. -->
  <div class="grid gap-3">
    <div class="flex flex-wrap items-center gap-3 rounded-md border bg-muted/20 px-3 py-2">
      <label class="flex select-none items-center gap-2 font-sans text-sm">
        <span class="text-muted-foreground">Corpus</span>
        <select
          class="h-8 rounded-md border bg-background px-2 text-sm"
          value={eval_.corpusSource}
          onchange={(e) =>
            eval_.setCorpusSource(e.currentTarget.value as 'synthetic' | 'adam')}
          disabled={isBusy}
        >
          <option value="adam">Adam (temporal · 35 episodes)</option>
          <option value="synthetic">Synthetic L3 (.md)</option>
        </select>
      </label>
      <label class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm">
        <input type="checkbox" class="size-4" bind:checked={eval_.ingestSynthetic} disabled={isBusy} />
        <span>
          {eval_.corpusSource === 'adam'
            ? 'Ingest corpus (episodes → Qdrant + graph)'
            : 'Ingest synthetic corpus'}
        </span>
      </label>
      {#if eval_.corpusSource === 'synthetic'}
        <label class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm">
          <input type="checkbox" class="size-4" bind:checked={eval_.buildGraph} disabled={isBusy} />
          <span>Build graph</span>
        </label>
      {/if}
      <!-- Leg selector — compare any subset of flat/graphiti (one is fine). -->
      <div class="flex items-center gap-2 font-sans text-sm">
        <span class="text-muted-foreground">Legs</span>
        <div class="flex gap-1" role="group" aria-label="Legs to compare">
          {#each EVAL_ALL_LEGS as mode (mode)}
            <button
              type="button"
              class="rounded-md border px-2 py-1 text-xs {eval_.isModeSelected(mode)
                ? 'border-primary bg-primary/10 text-primary'
                : 'text-muted-foreground hover:bg-muted'}"
              aria-pressed={eval_.isModeSelected(mode)}
              disabled={isBusy}
              title={mode === 'graphiti'
                ? 'Graph facts only (by-id passages, no query hybrid)'
                : 'No graph — flat Qdrant hybrid'}
              onclick={() => eval_.toggleMode(mode)}
            >
              {legLabel(mode)}
            </button>
          {/each}
        </div>
      </div>
      <div class="ml-auto flex gap-2">
        {#if eval_.rows.length > 0 || eval_.summary || eval_.failureMessage}
          <Button variant="outline" disabled={isBusy} onclick={eval_.clear} title="Clear the last run's results">
            <Trash2 size={14} /> Clear
          </Button>
        {/if}
        {#if isBusy}
          <Button
            variant="destructive"
            disabled={eval_.cancelling}
            onclick={() => void eval_.cancel()}
            title="Stop the running eval"
          >
            {#if eval_.cancelling}
              <LoaderCircle size={14} class="animate-spin" />
            {:else}
              <Square size={14} />
            {/if}
            {eval_.cancelling ? 'Cancelling…' : 'Cancel'}
          </Button>
        {/if}
        <Button disabled={!canRun} onclick={() => void eval_.start()}>
          {#if isBusy}
            <LoaderCircle size={14} class="animate-spin" />
          {:else}
            <Play size={14} />
          {/if}
          Run eval
        </Button>
      </div>
    </div>

    <!-- Question checklist (Adam path only). Empty selection = run all. Cap 50. -->
    {#if eval_.corpusSource === 'adam'}
      <div class="rounded-md border">
        <div
          class="flex flex-wrap items-center gap-2 bg-muted/30 px-3 py-1.5 text-xs {questionsCollapsed
            ? ''
            : 'border-b'}"
        >
          <button
            type="button"
            class="flex items-center gap-1.5 font-semibold hover:text-primary"
            aria-expanded={!questionsCollapsed}
            aria-controls="knowledge-eval-questions-body"
            onclick={() => (questionsCollapsed = !questionsCollapsed)}
          >
            <ChevronRight
              size={13}
              class="shrink-0 text-muted-foreground transition-transform {questionsCollapsed
                ? ''
                : 'rotate-90'}"
              aria-hidden="true"
            />
            Questions
          </button>
          <span class="text-muted-foreground">
            {eval_.selectedCount}/{EVAL_MAX_SELECTED} selected{#if eval_.selectedCount === 0}
              · none = run all{/if}
          </span>
          {#if eval_.questionsLoading}
            <LoaderCircle size={12} class="animate-spin" aria-hidden="true" />
          {/if}
          <div class="ml-auto flex gap-2">
            <button
              type="button"
              class="rounded border px-2 py-0.5 hover:bg-muted disabled:opacity-50"
              disabled={eval_.selectedCount === 0 || isBusy}
              onclick={eval_.clearSelection}
            >
              Clear selection
            </button>
            <button
              type="button"
              class="rounded border px-2 py-0.5 hover:bg-muted disabled:opacity-50"
              disabled={isBusy}
              onclick={() => void eval_.loadQuestions()}
            >
              Reload
            </button>
          </div>
        </div>
        <div id="knowledge-eval-questions-body" hidden={questionsCollapsed}>
        {#if eval_.questionsError}
          <p class="px-3 py-2 text-xs text-destructive">{eval_.questionsError}</p>
        {:else if eval_.questions.length === 0 && !eval_.questionsLoading}
          <p class="px-3 py-2 text-xs text-muted-foreground">No questions loaded.</p>
        {:else}
          <div class="max-h-72 overflow-y-auto px-3 py-2">
            {#each groups as [category, items] (category)}
              <div class="mb-2">
                <label
                  class="flex select-none items-center gap-2 py-1 font-sans text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  <input
                    type="checkbox"
                    class="size-3.5"
                    checked={categoryAllSelected(items)}
                    disabled={isBusy}
                    onchange={(e) =>
                      eval_.setCategorySelected(
                        items.map((q) => q.id),
                        e.currentTarget.checked
                      )}
                  />
                  {category}
                  <span class="font-normal normal-case">({items.length})</span>
                </label>
                <div class="grid gap-0.5 pl-5">
                  {#each items as q (q.id)}
                    <label class="flex cursor-pointer select-none items-start gap-2 py-0.5 font-sans text-sm">
                      <input
                        type="checkbox"
                        class="mt-0.5 size-3.5"
                        checked={eval_.isSelected(q.id)}
                        disabled={isBusy}
                        onchange={() => eval_.toggleQuestion(q.id)}
                      />
                      <span class="min-w-0">
                        {q.question}
                        {#if q.subcategory}
                          <span class="text-xs text-muted-foreground"> · {q.subcategory}</span>
                        {/if}
                      </span>
                    </label>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        {/if}
        </div>
      </div>
    {/if}

    <!-- Failure banner (transport / setup). Per-question failures show as ✗ in the table. -->
    {#if eval_.status === 'failed' && eval_.failureMessage}
      <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
        Eval run failed: {eval_.failureMessage}
      </div>
    {/if}

    <!-- Live activity terminal — fine-grained setup + per-question progress.
         Shown whenever there's any activity; persists after the run completes. -->
    {#if isBusy || eval_.setupEvents.length > 0 || eval_.rows.length > 0}
      <KnowledgeAskEvalTerminal
        setupEvents={eval_.setupEvents}
        rows={eval_.rows}
        status={eval_.status}
        totalQuestions={eval_.totalQuestions}
        summaryGate={eval_.summary?.gate ?? null}
        summaryElapsedMs={eval_.summary?.elapsed_ms ?? null}
        failureMessage={eval_.failureMessage}
      />
    {/if}

    <!-- Live table (always visible once rows arrive — even after completion). -->
    {#if eval_.rows.length > 0 || eval_.status === 'running'}
      <div class="overflow-x-auto rounded-md border">
        <table class="w-full border-collapse font-sans text-sm">
          <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th class="px-2 py-1.5 text-left" title="▲ = requires graph (the L3 thesis test on this row)">▲</th>
              <th class="px-2 py-1.5 text-left">#</th>
              <th class="px-2 py-1.5 text-left">Question</th>
              <th class="px-2 py-1.5 text-left">Category</th>
              {#each legColumns as mode (mode)}
                <th class="px-2 py-1.5 text-center">{legLabel(mode)}</th>
              {/each}
              <th class="px-2 py-1.5 text-center" title="best graph leg vs flat">Δ</th>
              <th class="px-2 py-1.5 text-right">Links</th>
            </tr>
          </thead>
          <tbody>
            {#each eval_.rows as r (r.id)}
              <tr class="border-t">
                <td class="px-2 py-1.5 text-center">{r.requires_graph ? '▲' : ''}</td>
                <td class="px-2 py-1.5 font-mono tabular-nums text-xs text-muted-foreground">
                  {r.index + 1}/{r.total}
                </td>
                <td class="px-2 py-1.5">
                  <button
                    type="button"
                    class="flex w-full items-center gap-1.5 text-left hover:text-primary"
                    onclick={() => toggleRow(r.index)}
                    aria-expanded={expandedRows.has(r.index)}
                    title="Show full answers"
                  >
                    <ChevronRight
                      size={13}
                      class="shrink-0 text-muted-foreground transition-transform {expandedRows.has(
                        r.index
                      )
                        ? 'rotate-90'
                        : ''}"
                      aria-hidden="true"
                    />
                    <span class="line-clamp-1">{r.question}</span>
                  </button>
                </td>
                <td class="px-2 py-1.5 text-xs text-muted-foreground">{r.category}</td>
                {#each legColumns as mode (mode)}
                  <td class="px-2 py-1.5 text-center">
                    {#if r.legs[mode]}
                      <Badge variant={markVariant(r.legs[mode].mark)} class="font-mono">{r.legs[mode].mark}</Badge>
                      <span class="ml-1 font-mono text-xs tabular-nums text-muted-foreground">{r.legs[mode].elapsed_ms}ms</span>
                    {:else}
                      <span class="text-xs text-muted-foreground">—</span>
                    {/if}
                  </td>
                {/each}
                <td class="px-2 py-1.5 text-center">
                  <Badge variant={deltaVariant(r.delta)} class="font-mono">{r.delta}</Badge>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <div class="inline-flex gap-1">
                    {#each legColumns as mode (mode)}
                      {#if r.legs[mode]?.run_id}
                        <a
                          class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                          href={graphRunPageUrl(r.legs[mode].run_id!)}
                          title="{legLabel(mode)} leg Graph Run"
                        >
                          <ExternalLink size={10} aria-hidden="true" />{mode}
                        </a>
                      {/if}
                    {/each}
                  </div>
                </td>
              </tr>
              <!-- Detail row: full question + full per-leg answers. Kept in the
                   DOM (hidden) when collapsed so the toggle's aria-expanded target
                   stays stable. -->
              <tr class="border-t bg-muted/10" hidden={!expandedRows.has(r.index)}>
                <td colspan={tableColspan} class="px-3 py-3">
                  <div class="grid gap-3">
                    <div class="font-sans text-sm">
                      <span class="font-semibold">Q:</span>
                      {r.question}
                      {#if r.subcategory}
                        <span class="text-xs text-muted-foreground"> · {r.subcategory}</span>
                      {/if}
                    </div>
                    <!-- Scoring rubric: what each answer is judged against. -->
                    {#if r.expected_fragments.length > 0 || r.must_not_contain.length > 0}
                      <div class="flex flex-col gap-1 font-sans text-xs">
                        {#if r.expected_fragments.length > 0}
                          <div class="flex flex-wrap items-center gap-1">
                            <span class="font-semibold text-muted-foreground">Expected:</span>
                            {#each r.expected_fragments as frag (frag)}
                              <Badge variant="secondary" class="font-mono font-normal">{frag}</Badge>
                            {/each}
                          </div>
                        {/if}
                        {#if r.must_not_contain.length > 0}
                          <div class="flex flex-wrap items-center gap-1">
                            <span class="font-semibold text-muted-foreground">Must not contain:</span>
                            {#each r.must_not_contain as frag (frag)}
                              <Badge variant="warning" class="font-mono font-normal">{frag}</Badge>
                            {/each}
                          </div>
                        {/if}
                      </div>
                    {:else}
                      <div class="font-sans text-xs text-muted-foreground">
                        Negative control — abstaining is the expected (correct) outcome.
                      </div>
                    {/if}
                    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {#each legColumns as mode (mode)}
                        {#if r.legs[mode]}
                          {@render answerCell(
                            legLabel(mode),
                            r.legs[mode].mark,
                            r.legs[mode].elapsed_ms,
                            r.legs[mode].answer,
                            r.legs[mode].run_id
                          )}
                        {/if}
                      {/each}
                    </div>
                  </div>
                </td>
              </tr>
            {/each}
            {#if eval_.status === 'running' && eval_.totalQuestions > eval_.rows.length}
              <tr class="border-t bg-muted/10">
                <td colspan={tableColspan} class="px-2 py-2 text-center font-sans text-xs text-muted-foreground">
                  <LoaderCircle size={12} class="mr-1 inline animate-spin" aria-hidden="true" />
                  {eval_.rows.length} / {eval_.totalQuestions} done · waiting for next…
                </td>
              </tr>
            {/if}
          </tbody>
        </table>
      </div>
    {/if}

    <!-- Summary / gate verdict. Per-leg passing on the requires_graph subset is
         what determines proceed/pivot; the gate is 'n/a' when the run can't
         compare (e.g. a single leg, or no flat baseline). -->
    {#if eval_.summary}
      {@const s = eval_.summary}
      <div
        class="grid gap-2 rounded-md border px-3 py-3 font-sans text-sm {s.gate === 'proceed'
          ? 'border-emerald-500/40 bg-emerald-500/5'
          : s.gate === 'pivot'
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-muted/20'}"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-base font-semibold">
            {s.gate === 'proceed' ? '✅ PROCEED' : s.gate === 'pivot' ? '❌ PIVOT' : 'ℹ️ Results'}
          </span>
          <span class="text-xs text-muted-foreground">legs: {s.modes.map(legLabel).join(' · ')}</span>
          <Badge variant="outline" class="font-mono">{s.elapsed_ms}ms</Badge>
        </div>
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            Passing (all {s.total_questions}):
            {#each s.modes as mode (mode)}
              <span class="ml-1 font-mono">{legLabel(mode)}={s.passing?.[mode] ?? 0}</span>
            {/each}
          </span>
          <span>
            On <code class="font-mono">requires_graph</code> ({s.requires_graph_total}):
            {#each s.modes as mode (mode)}
              <span class="ml-1 font-mono">{legLabel(mode)}={s.requires_graph_passing?.[mode] ?? 0}</span>
            {/each}
          </span>
        </div>
      </div>
    {/if}

    <!-- Per-category × N-leg breakdown (where each leg helps). -->
    {#if eval_.summary?.by_category && Object.keys(eval_.summary.by_category).length > 0}
      {@const bc = eval_.summary.by_category}
      {@const cols = eval_.summary.modes}
      <div class="overflow-x-auto rounded-md border">
        <table class="w-full border-collapse font-sans text-sm">
          <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th class="px-2 py-1.5 text-left">Category</th>
              {#each cols as mode (mode)}
                <th class="px-2 py-1.5 text-center">{legLabel(mode)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(bc) as [cat, st] (cat)}
              {@const flatPass = st.pass?.flat ?? 0}
              <tr class="border-t">
                <td class="px-2 py-1.5">{cat}</td>
                {#each cols as mode (mode)}
                  <td
                    class="px-2 py-1.5 text-center font-mono tabular-nums {mode !== 'flat' &&
                    (st.pass?.[mode] ?? 0) > flatPass
                      ? 'font-semibold text-emerald-600'
                      : 'text-muted-foreground'}"
                  >
                    {st.pass?.[mode] ?? 0}/{st.total}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    {#if eval_.status === 'idle' && eval_.rows.length === 0 && !eval_.failureMessage}
      <p class="rounded-md border border-dashed px-3 py-6 text-center font-sans text-xs text-muted-foreground">
        {#if eval_.corpusSource === 'adam'}
          Ingests the 35-episode Adam corpus (Qdrant + Graphiti) and runs the selected questions
          across the chosen legs. Pick the legs to compare (flat / graphiti — either or both)
          and the questions (or leave all unselected to run every one), check "Ingest corpus"
          on the first run, then Run. Results stream live with a per-category breakdown and a
          PROCEED/PIVOT verdict (when flat + a graph leg are both selected).
        {:else}
          Runs the synthetic questions from <code class="font-mono">eval/l3_questions.yaml</code>
          across the chosen legs (flat / graphiti). First run: check both setup boxes.
          Subsequent runs: leave them off (graph and corpus stay in the workspace).
        {/if}
      </p>
    {/if}
  </div>
</KnowledgeCollapsibleSectionCard>

<!-- Full-answer cell for an expanded table row. Answers render as plain
     pre-wrapped text (matching the compare view) — no markdown pipeline, so no
     {@html} / sanitizer boundary to maintain. -->
{#snippet answerCell(
  title: string,
  mark: string,
  ms: number,
  answer: string,
  runId: string | null
)}
  <div class="grid content-start gap-1 rounded-md border bg-background p-2.5">
    <div class="flex items-center gap-2">
      <span class="font-sans text-xs font-semibold">{title}</span>
      <Badge variant={markVariant(mark)} class="font-mono">{mark}</Badge>
      <span class="font-mono text-xs tabular-nums text-muted-foreground">{ms}ms</span>
      {#if runId}
        <a
          class="ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
          href={graphRunPageUrl(runId)}
          title={runId}
        >
          <ExternalLink size={10} aria-hidden="true" /> run
        </a>
      {/if}
    </div>
    <p class="max-h-80 overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-6">
      {answer || '— (no answer)'}
    </p>
  </div>
{/snippet}
