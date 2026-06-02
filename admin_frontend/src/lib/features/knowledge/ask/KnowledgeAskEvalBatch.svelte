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
  import { ExternalLink, LoaderCircle, Play, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { EvalQuestionItem } from '$lib/api/knowledge';
  import {
    createKnowledgeEvalModel,
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
  // Load the question bank once (for the checklist) when the panel mounts.
  onMount(() => {
    if (eval_.corpusSource === 'adam') void eval_.loadQuestions();
  });

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
      case 'completed':
        return eval_.summary
          ? `${eval_.summary.gate === 'proceed' ? '✅ PROCEED' : '❌ PIVOT'} · ${eval_.summary.elapsed_ms}ms`
          : 'Done';
      case 'failed':
        return '❌ Failed';
    }
  });

  const canRun = $derived(eval_.status === 'idle' || eval_.status === 'completed' || eval_.status === 'failed');
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
      <div class="ml-auto flex gap-2">
        {#if eval_.rows.length > 0 || eval_.summary || eval_.failureMessage}
          <Button variant="outline" disabled={isBusy} onclick={eval_.clear} title="Clear the last run's results">
            <Trash2 size={14} /> Clear
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
        <div class="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-3 py-1.5 text-xs">
          <span class="font-semibold">Questions</span>
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
    {/if}

    <!-- Failure banner (transport / setup). Per-question failures show as ✗ in the table. -->
    {#if eval_.status === 'failed' && eval_.failureMessage}
      <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
        Eval run failed: {eval_.failureMessage}
      </div>
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
              <th class="px-2 py-1.5 text-center" title="flat (graph: off)">Flat</th>
              <th class="px-2 py-1.5 text-center" title="graph-augmented (graph: on)">Graph</th>
              <th class="px-2 py-1.5 text-center">Δ</th>
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
                <td class="px-2 py-1.5"><span class="line-clamp-1">{r.question}</span></td>
                <td class="px-2 py-1.5 text-xs text-muted-foreground">{r.category}</td>
                <td class="px-2 py-1.5 text-center">
                  <Badge variant={markVariant(r.flatMark)} class="font-mono">{r.flatMark}</Badge>
                  <span class="ml-1 font-mono text-xs tabular-nums text-muted-foreground">{r.flatElapsedMs}ms</span>
                </td>
                <td class="px-2 py-1.5 text-center">
                  <Badge variant={markVariant(r.graphMark)} class="font-mono">{r.graphMark}</Badge>
                  <span class="ml-1 font-mono text-xs tabular-nums text-muted-foreground">{r.graphElapsedMs}ms</span>
                </td>
                <td class="px-2 py-1.5 text-center">
                  <Badge variant={deltaVariant(r.delta)} class="font-mono">{r.delta}</Badge>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <div class="inline-flex gap-1">
                    {#if r.flatRunId}
                      <a
                        class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                        href={graphRunPageUrl(r.flatRunId)}
                        title="Flat leg Graph Run"
                      >
                        <ExternalLink size={10} aria-hidden="true" />flat
                      </a>
                    {/if}
                    {#if r.graphRunId}
                      <a
                        class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                        href={graphRunPageUrl(r.graphRunId)}
                        title="Graph leg Graph Run"
                      >
                        <ExternalLink size={10} aria-hidden="true" />graph
                      </a>
                    {/if}
                  </div>
                </td>
              </tr>
            {/each}
            {#if eval_.status === 'running' && eval_.totalQuestions > eval_.rows.length}
              <tr class="border-t bg-muted/10">
                <td colspan="8" class="px-2 py-2 text-center font-sans text-xs text-muted-foreground">
                  <LoaderCircle size={12} class="mr-1 inline animate-spin" aria-hidden="true" />
                  {eval_.rows.length} / {eval_.totalQuestions} done · waiting for next…
                </td>
              </tr>
            {/if}
          </tbody>
        </table>
      </div>
    {/if}

    <!-- Summary / gate verdict.
         The gate text matches the CLI harness: graph_passing vs flat_passing
         on the requires_graph subset is what determines proceed/pivot. -->
    {#if eval_.summary}
      {@const s = eval_.summary}
      <div
        class="grid gap-2 rounded-md border px-3 py-3 font-sans text-sm {s.gate === 'proceed'
          ? 'border-emerald-500/40 bg-emerald-500/5'
          : 'border-amber-500/40 bg-amber-500/5'}"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-base font-semibold">
            {s.gate === 'proceed' ? '✅ PROCEED' : '❌ PIVOT'}
          </span>
          <Badge variant="outline" class="font-mono">{s.elapsed_ms}ms</Badge>
        </div>
        <div class="text-xs text-muted-foreground">
          Graph beats flat on the <code class="font-mono">requires_graph</code> subset:
          <span class="font-mono">graph={s.requires_graph_graph_passing}</span> ·
          <span class="font-mono">flat={s.requires_graph_flat_passing}</span> ·
          (of <span class="font-mono">{s.requires_graph_total}</span> required rows).
          Across all <span class="font-mono">{s.total_questions}</span> questions:
          graph wins <span class="font-mono">{s.graph_wins}</span> · ties
          <span class="font-mono">{s.ties}</span> · loses
          <span class="font-mono">{s.graph_loses}</span>.
        </div>
      </div>
    {/if}

    <!-- Per-category × flat/graph breakdown (where graph helps). -->
    {#if eval_.summary?.by_category && Object.keys(eval_.summary.by_category).length > 0}
      {@const bc = eval_.summary.by_category}
      <div class="overflow-x-auto rounded-md border">
        <table class="w-full border-collapse font-sans text-sm">
          <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th class="px-2 py-1.5 text-left">Category</th>
              <th class="px-2 py-1.5 text-center">Flat</th>
              <th class="px-2 py-1.5 text-center">Graph</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(bc) as [cat, st] (cat)}
              <tr class="border-t">
                <td class="px-2 py-1.5">{cat}</td>
                <td class="px-2 py-1.5 text-center font-mono tabular-nums text-muted-foreground">
                  {st.flat_pass}/{st.total}
                </td>
                <td
                  class="px-2 py-1.5 text-center font-mono tabular-nums {st.graph_pass > st.flat_pass
                    ? 'font-semibold text-emerald-600'
                    : ''}"
                >
                  {st.graph_pass}/{st.total}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    {#if eval_.status === 'idle' && eval_.rows.length === 0 && !eval_.failureMessage}
      <p class="rounded-md border border-dashed px-3 py-6 text-center font-sans text-xs text-muted-foreground">
        {#if eval_.corpusSource === 'adam'}
          Ingests the 35-episode Adam corpus (Qdrant + Graphiti) and runs the selected questions in
          compare mode (flat vs graph). Pick questions above (or leave all unselected to run every
          one), check "Ingest corpus" on the first run, then Run. Results stream live with a
          per-category breakdown and a PROCEED/PIVOT verdict.
        {:else}
          Runs the synthetic questions from <code class="font-mono">eval/l3_questions.yaml</code> in
          compare mode (flat vs graph-augmented). First run: check both setup boxes. Subsequent runs:
          leave them off (graph and corpus stay in the workspace).
        {/if}
      </p>
    {/if}
  </div>
</KnowledgeCollapsibleSectionCard>
