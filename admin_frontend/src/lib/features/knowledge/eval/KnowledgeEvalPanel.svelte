<!--
  L3 prototype (Phase 5e) — Eval Batch tab.

  Its own Knowledge tab (moved out of the Ask tab). Three phases of UI:

    1. idle  → setup checkboxes (ingest synthetic / build graph) + Run button
    2. running → live progress table; rows append/update as
                 ``knowledge.eval.question_completed`` events arrive
    3. completed → final summary card with PROCEED/PIVOT gate verdict

  All transport plumbing lives in the controller (`knowledge-eval.svelte.ts`);
  this component is a thin view.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { base } from '$app/paths';
  import {
    ChevronRight,
    ExternalLink,
    FolderSearch,
    LoaderCircle,
    Play,
    RefreshCw,
    Settings2,
    Square,
    Trash2
  } from '@lucide/svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import KnowledgeEvalTerminal from '$lib/features/knowledge/eval/KnowledgeEvalTerminal.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import type { EvalQuestionItem } from '$lib/api/knowledge';
  import type { EvalCompletedPayload } from '$lib/features/knowledge/shared/knowledge-events';
  import { getPreferences, type WorkspacePreferences } from '$lib/api/preferences';
  import {
    createKnowledgeEvalModel,
    EVAL_ALL_LEGS,
    EVAL_LEG_LABEL,
    type EvalTrack,
    type KnowledgeEvalModel
  } from '$lib/features/knowledge/state/knowledge-eval.svelte';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  // Wrap in a closure so the controller captures the *live* reference (Svelte 5
  // ``state_referenced_locally`` rule — bare ``{ setError }`` would snapshot the
  // initial value at controller-construction time). The Knowledge page owns the
  // shared error display.
  const eval_: KnowledgeEvalModel = createKnowledgeEvalModel({
    setError: (msg) => ctl.setError(msg)
  });

  // Engine preferences shown at the top (read-only) so the user sees exactly which
  // settings drive this run, with a link to change them. Loaded once on mount.
  let prefs = $state<WorkspacePreferences | null>(null);
  async function loadPrefs() {
    try {
      const res = await getPreferences();
      prefs = res.data.preferences;
    } catch {
      prefs = null; // non-fatal — the panel still works without the params strip
    }
  }

  onDestroy(() => eval_.teardown());
  onMount(() => {
    // Subscribe to live events + replay the server-side run state (survives
    // navigation mid-run; consistent across the Vite/packaged origins); init() also
    // scans the corpus picker for the current track.
    void eval_.init();
    void loadPrefs();
  });

  // The shared knowledge SSE is paused while this browser tab is hidden (to free the
  // per-origin connection budget so other tabs don't stall). A run keeps progressing
  // server-side meanwhile, so on refocus we re-pull the authoritative run state to
  // backfill any events missed while backgrounded.
  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible') void eval_.resync();
  }

  const TRACK_TABS: { id: EvalTrack; label: string }[] = [
    { id: 'memory', label: 'Memory' },
    { id: 'knowledge', label: 'Knowledge' }
  ];

  // Per-row expansion (full answers). Keyed by question index; reassigned on
  // mutation so Svelte 5 tracks the Set.
  let expandedRows = $state<Set<number>>(new Set());
  function toggleRow(index: number) {
    const next = new Set(expandedRows);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    expandedRows = next;
  }

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
        if (eval_.setupPhase?.phase === 'remember') return 'Rebuilding graph…';
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
        if (eval_.summary.track === 'memory')
          return `Recalled ${eval_.summary.recalled_for ?? 0}/${eval_.summary.total_questions} · ${eval_.summary.elapsed_ms}ms`;
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

  // Questions-card header summary: selection count out of the corpus total (no cap;
  // a non-empty selection is required to run).
  const questionsSummary = $derived(
    `${eval_.selectedCount}/${eval_.questions.length} selected${
      eval_.selectedCount === 0 ? ' · select at least one' : ''
    }`
  );

  // Engine params strip — the preference values that actually drive this run, per track.
  type Param = { label: string; value: string };
  const engineParams = $derived.by<Param[]>(() => {
    if (!prefs) return [];
    const g = prefs.graph;
    const dash = (v: string | null | undefined) => (v && String(v).trim() ? String(v) : '—');
    const common: Param[] = [
      { label: 'Graph backend', value: g.backend },
      { label: 'Extraction model', value: dash(g.extraction_model) },
      { label: 'Embedder', value: dash(g.embedder_model) }
    ];
    if (isMemory) {
      return [
        ...common,
        { label: 'Recall top-k', value: String(prefs.memory.search.top_k) },
        { label: 'Temporal lens', value: 'current' },
        { label: 'Sim floor', value: String(g.sim_min_score) },
        { label: 'Search scope', value: g.search_scope }
      ];
    }
    return [
      ...common,
      { label: 'Retrieval top-k', value: String(prefs.knowledge.retrieval.top_k) },
      { label: 'Search recipe', value: g.search_recipe },
      { label: 'Sim floor', value: String(g.sim_min_score) }
    ];
  });

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

  // The memory track is a single recall leg: no flat/graphiti legs, no Δ, no gate.
  const isMemory = $derived(eval_.track === 'memory');

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
    return EVAL_LEG_LABEL[mode] ?? mode.charAt(0).toUpperCase() + mode.slice(1);
  }

  // Columns for the results table = the legs the current run used (memory = ['recall']).
  const legColumns = $derived(eval_.runModes);
  // Δ (best graph leg vs flat) only makes sense on the knowledge track (multi-leg compare).
  const showDelta = $derived(!isMemory);
  // Full-width row colspan: ▲, #, Question, Ideal, <N legs>, [Δ], Links.
  const resultsColspan = $derived(4 + legColumns.length + (showDelta ? 1 : 0) + 1);

</script>

<svelte:document onvisibilitychange={onVisibilityChange} />

<section class="grid gap-4">
  <!-- Track sub-tabs — Memory vs Knowledge select the whole panel's shape. -->
  <div
    role="tablist"
    aria-label="Eval track"
    class="flex w-fit gap-1 rounded-lg border bg-muted/30 p-1 font-sans text-sm"
  >
    {#each TRACK_TABS as t (t.id)}
      <button
        type="button"
        role="tab"
        aria-selected={eval_.track === t.id}
        disabled={isBusy}
        class="rounded-md px-3 py-1.5 transition-colors disabled:opacity-50 {eval_.track === t.id
          ? 'bg-background font-semibold text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'}"
        onclick={() => eval_.setTrack(t.id)}
      >
        {t.label}
      </button>
    {/each}
  </div>

  <!-- Engine parameters that drive this run (read-only) + a link to change them. -->
  {#if engineParams.length > 0}
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
      <span class="font-semibold uppercase tracking-wide text-muted-foreground">Engine</span>
      {#each engineParams as p (p.label)}
        <span class="text-muted-foreground">
          {p.label}: <span class="font-mono text-foreground">{p.value}</span>
        </span>
      {/each}
      <a
        href="{base}/preferences"
        class="ml-auto inline-flex items-center gap-1 rounded border px-2 py-0.5 text-primary hover:bg-primary/5"
        title="Change these in workspace settings"
      >
        <Settings2 size={12} aria-hidden="true" /> Settings
      </a>
    </div>
  {/if}

  <!-- Corpus picker + run controls. Inputs disable while a run is in flight. -->
  <AdminPageStickyToolbar>
    <div class="flex flex-wrap items-center gap-3">
      <!-- Folder: text input + native pick (like Knowledge Add) + rescan. -->
      <div class="flex items-center gap-1.5 font-sans text-sm">
        <span class="text-muted-foreground">Folder</span>
        <input
          class="h-8 w-64 rounded-md border bg-background px-2 text-sm"
          placeholder="Folder to scan for corpuses"
          value={eval_.folder}
          oninput={(e) => eval_.setFolder(e.currentTarget.value)}
          onchange={() => void eval_.scanCorpuses()}
          disabled={isBusy}
        />
        <Button
          type="button"
          variant="outline"
          class="h-8"
          onclick={() => void eval_.browseFolder()}
          disabled={isBusy || eval_.pickingFolder}
          title="Pick a folder"
        >
          {#if eval_.pickingFolder}
            <LoaderCircle size={14} class="animate-spin" />
          {:else}
            <FolderSearch size={14} />
          {/if}
        </Button>
        <Button
          type="button"
          variant="outline"
          class="h-8"
          onclick={() => void eval_.scanCorpuses()}
          disabled={isBusy || eval_.corpusesLoading}
          title="Rescan folder"
        >
          <RefreshCw size={14} class={eval_.corpusesLoading ? 'animate-spin' : ''} />
        </Button>
      </div>

      <!-- Corpus dropdown — the corpuses found in the folder for this track. -->
      <label class="flex select-none items-center gap-2 font-sans text-sm">
        <span class="text-muted-foreground">Corpus</span>
        <select
          class="h-8 min-w-48 rounded-md border bg-background px-2 text-sm disabled:opacity-50"
          value={eval_.selectedCorpusId}
          onchange={(e) => eval_.selectCorpus(e.currentTarget.value)}
          disabled={isBusy || eval_.corpuses.length === 0}
        >
          {#if eval_.corpuses.length === 0}
            <option value="">No corpuses found</option>
          {:else}
            {#each eval_.corpuses as c (c.id)}
              <option value={c.id}>
                {c.name} ({c.item_count} {isMemory ? 'episodes' : 'docs'} · {c.question_count} Qs)
              </option>
            {/each}
          {/if}
        </select>
      </label>

      <label
        class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm"
        title={isMemory
          ? 'Wipe this set’s memory graph, then re-remember the turns from scratch. Leave off to recall the existing graph (e.g. re-run a question subset).'
          : 'Wipe this corpus’s eval docs (chunks + graph), then re-ingest from scratch. Leave off to reuse the existing index.'}
      >
        <input type="checkbox" class="size-4" bind:checked={eval_.ingestSynthetic} disabled={isBusy} />
        <span>{isMemory ? 'Rebuild graph' : 'Ingest corpus first'}</span>
      </label>
      {#if !isMemory}
        <label
          class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm"
          title="Wipe this corpus's prior graph, then rebuild it from the ingested chunks. Leave off to reuse the existing graph."
        >
          <input type="checkbox" class="size-4" bind:checked={eval_.buildGraph} disabled={isBusy} />
          <span>Rebuild graph</span>
        </label>
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
      {:else}
        <span
          class="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-2 py-1 font-sans text-xs text-primary"
          title="Conversation memory recall — the single engine the memory track exercises"
        >
          <span class="size-1.5 rounded-full bg-primary"></span> Recall
        </span>
      {/if}
      <!-- Optional LLM judge — grades each answer vs the ideal (reuses the answering model). -->
      <label
        class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm"
        title="Grade the model's answer against the ideal answer (extra LLM call per question). Off = answers only, no marks."
      >
        <input type="checkbox" class="size-4" bind:checked={eval_.judge} disabled={isBusy} />
        <span>Judge answers</span>
      </label>
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
        <Button
          disabled={!canRun || !eval_.selectedCorpus || eval_.selectedCount === 0}
          onclick={() => void eval_.start()}
          title={eval_.selectedCount === 0 ? 'Select at least one question' : 'Run the eval'}
        >
          {#if isBusy}
            <LoaderCircle size={14} class="animate-spin" />
          {:else}
            <Play size={14} />
          {/if}
          Run eval
        </Button>
      </div>
    </div>
  </AdminPageStickyToolbar>

  <!-- Failure banner (transport / setup). Per-question failures show as ✗ in the table. -->
  {#if eval_.status === 'failed' && eval_.failureMessage}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
      Eval run failed: {eval_.failureMessage}
    </div>
  {/if}

  <!-- Corpus / questions errors (scan + bank). -->
  {#if eval_.corpusesError}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
      {eval_.corpusesError}
    </div>
  {/if}

  <!-- Questions section — pick the questions to run (required; no implicit "run all"). -->
  {#if eval_.selectedCorpus}
    <KnowledgeCollapsibleSectionCard
      title="Questions"
      bodyId="knowledge-eval-questions"
      defaultExpanded={true}
      summary={questionsSummary}
    >
      {#snippet headerActions()}
        {#if eval_.questionsLoading}
          <LoaderCircle size={14} class="animate-spin text-muted-foreground" aria-hidden="true" />
        {/if}
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
          disabled={eval_.selectedCount === 0 || isBusy}
          onclick={eval_.clearSelection}
        >
          Clear selection
        </button>
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
          disabled={isBusy}
          onclick={() => void eval_.loadQuestions()}
        >
          Reload
        </button>
      {/snippet}
      {#if eval_.questionsError}
        <p class="text-xs text-destructive">{eval_.questionsError}</p>
      {:else if eval_.questions.length === 0 && !eval_.questionsLoading}
        <p class="text-xs text-muted-foreground">No questions loaded.</p>
      {:else}
        <div class="max-h-96 overflow-y-auto rounded-md border px-3 py-2">
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
    </KnowledgeCollapsibleSectionCard>
  {/if}

  <!-- Activity section — only once processing starts (or has data to replay). Persists
       across navigation via the server-side run registry (GET /knowledge/eval/state). -->
  {#if isBusy || eval_.setupEvents.length > 0 || eval_.rows.length > 0}
    <KnowledgeCollapsibleSectionCard
      title="Activity"
      bodyId="knowledge-eval-activity"
      defaultExpanded={true}
      summary={headerSummary}
    >
      <KnowledgeEvalTerminal
        setupEvents={eval_.setupEvents}
        rows={eval_.rows}
        status={eval_.status}
        totalQuestions={eval_.totalQuestions}
        summaryGate={eval_.summary?.gate ?? null}
        summaryElapsedMs={eval_.summary?.elapsed_ms ?? null}
        failureMessage={eval_.failureMessage}
      />
    </KnowledgeCollapsibleSectionCard>
  {/if}

  <!-- Results — unified across tracks: Question, Ideal, Model answer(s) at a glance;
       fold for recalled facts / judge reason / full answers / run links. -->
  {#if eval_.rows.length > 0 || eval_.summary}
    <KnowledgeCollapsibleSectionCard
      title="Results"
      bodyId="knowledge-eval-results"
      defaultExpanded={true}
      summary={resultsSummary}
    >
      {#if eval_.rows.length > 0 || eval_.status === 'running'}
        {@render resultsTable()}
      {/if}
      {#if eval_.summary}
        {@render summaryCard(eval_.summary)}
      {/if}
      {#if eval_.summary?.by_category && Object.keys(eval_.summary.by_category).length > 0}
        {@render categoryBreakdown(eval_.summary.by_category, eval_.summary.modes)}
      {/if}
    </KnowledgeCollapsibleSectionCard>
  {/if}
</section>

<!-- Unified results table: Question, Ideal, per-leg [mark + model answer]; fold for details. -->
{#snippet resultsTable()}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1.5 text-left" title="requires graph/temporal reasoning">&#9650;</th>
          <th class="px-2 py-1.5 text-left">#</th>
          <th class="px-2 py-1.5 text-left">Question</th>
          <th class="px-2 py-1.5 text-left">Ideal</th>
          {#each legColumns as mode (mode)}
            <th class="px-2 py-1.5 text-left">{legLabel(mode)} answer</th>
          {/each}
          {#if showDelta}<th class="px-2 py-1.5 text-center" title="best graph leg vs flat">&#916;</th>{/if}
          <th class="px-2 py-1.5 text-right">Links</th>
        </tr>
      </thead>
      <tbody>
        {#each eval_.rows as r (r.id)}
          <tr class="border-t align-top">
            <td class="px-2 py-1.5 text-center">
              {r.requires_graph ? '▲' : ''}{#if r.stale_hit}<span class="ml-0.5 text-amber-600" title="possible superseded-fact leak">&#9888;</span>{/if}
            </td>
            <td class="px-2 py-1.5 font-mono tabular-nums text-xs text-muted-foreground">{r.index + 1}/{r.total}</td>
            <td class="max-w-[22rem] px-2 py-1.5">
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
                <span class="line-clamp-2">{r.question}</span>
              </button>
            </td>
            <td class="max-w-[16rem] px-2 py-1.5 text-xs text-muted-foreground">
              <span class="line-clamp-2">{r.gold || '—'}</span>
            </td>
            {#each legColumns as mode (mode)}
              <td class="max-w-[20rem] px-2 py-1.5">
                {#if r.legs[mode]}
                  {@const leg = r.legs[mode]}
                  <div class="flex items-start gap-1.5">
                    <Badge variant={markVariant(leg.mark)} class="mt-0.5 font-mono">{leg.mark || '—'}</Badge>
                    <span class="line-clamp-2 text-sm">{leg.answer || '— (no answer)'}</span>
                  </div>
                {:else}
                  <span class="text-xs text-muted-foreground">—</span>
                {/if}
              </td>
            {/each}
            {#if showDelta}
              <td class="px-2 py-1.5 text-center">
                <Badge variant={deltaVariant(r.delta)} class="font-mono">{r.delta}</Badge>
              </td>
            {/if}
            <td class="px-2 py-1.5 text-right">
              <div class="inline-flex gap-1">
                {#each legColumns as mode (mode)}
                  {#if r.legs[mode]?.run_id}
                    <a
                      class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                      href={graphRunPageUrl(r.legs[mode].run_id!)}
                      title="{legLabel(mode)} Graph Run"
                    >
                      <ExternalLink size={10} aria-hidden="true" />{mode}
                    </a>
                  {/if}
                {/each}
              </div>
            </td>
          </tr>
          <!-- Fold: per-leg judge verdict + recalled facts (expanded). Question/ideal/answer are
               already in the row above, so we don't repeat them here — only the diagnostic detail. -->
          <tr class="border-t bg-muted/10" hidden={!expandedRows.has(r.index)}>
            <td colspan={resultsColspan} class="px-3 py-3">
              <div class="grid gap-3">
                {#if r.subcategory || r.must_not_contain.length > 0}
                  <div class="flex flex-wrap items-center gap-2 font-sans text-xs">
                    {#if r.subcategory}<span class="text-muted-foreground">{r.subcategory}</span>{/if}
                    {#if r.must_not_contain.length > 0}
                      <span class="font-semibold text-muted-foreground">Must not contain:</span>
                      {#each r.must_not_contain as frag (frag)}
                        <Badge variant="warning" class="font-mono font-normal">{frag}</Badge>
                      {/each}
                    {/if}
                  </div>
                {/if}
                {#if r.stale_hit}
                  <div class="rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1 font-sans text-xs text-amber-700">
                    &#9888; a recalled fact contains a must-not-surface value &mdash; possible superseded-fact leak
                  </div>
                {/if}
                <div class="grid gap-3 md:grid-cols-2">
                  {#each legColumns as mode (mode)}
                    {#if r.legs[mode]}
                      {@const leg = r.legs[mode]}
                      <div class="grid content-start gap-1.5 rounded-md border bg-background p-2.5">
                        <div class="flex items-center gap-2">
                          <span class="font-sans text-xs font-semibold">{legLabel(mode)}</span>
                          <Badge variant={markVariant(leg.mark)} class="font-mono">{leg.mark || '—'}</Badge>
                          <span class="font-mono text-xs tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
                          {#if leg.run_id}
                            <a
                              class="ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                              href={graphRunPageUrl(leg.run_id)}
                              title="Graph Run"
                            >
                              <ExternalLink size={10} aria-hidden="true" /> run
                            </a>
                          {/if}
                        </div>
                        {#if leg.reason}
                          <p class="text-xs leading-6 text-muted-foreground"><span class="font-semibold">Judge:</span> {leg.reason}</p>
                        {:else}
                          <p class="text-xs italic text-muted-foreground">No judge verdict.</p>
                        {/if}
                        {#if (leg.recalled ?? []).length > 0}
                          <div class="text-xs">
                            <div class="font-semibold text-muted-foreground">Recalled facts ({(leg.recalled ?? []).length})</div>
                            <ul class="ml-4 mt-1 list-disc leading-6">
                              {#each leg.recalled ?? [] as f, i (i)}<li>{f}</li>{/each}
                            </ul>
                          </div>
                        {:else}
                          <div class="text-xs italic text-muted-foreground">No recalled facts.</div>
                        {/if}
                      </div>
                    {/if}
                  {/each}
                </div>
              </div>
            </td>
          </tr>
        {/each}
        {#if eval_.status === 'running' && eval_.totalQuestions > eval_.rows.length}
          <tr class="border-t bg-muted/10">
            <td colspan={resultsColspan} class="px-2 py-2 text-center font-sans text-xs text-muted-foreground">
              <LoaderCircle size={12} class="mr-1 inline animate-spin" aria-hidden="true" />
              {eval_.rows.length} / {eval_.totalQuestions} done &middot; waiting for next&hellip;
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
{/snippet}

<!-- Summary: knowledge PROCEED/PIVOT gate or memory recall counts; both note when judge is off. -->
{#snippet summaryCard(s: EvalCompletedPayload)}
  {@const judged = s.judged ?? true}
  <div
    class="grid gap-2 rounded-md border px-3 py-3 font-sans text-sm {s.gate === 'proceed'
      ? 'border-emerald-500/40 bg-emerald-500/5'
      : s.gate === 'pivot'
        ? 'border-amber-500/40 bg-amber-500/5'
        : 'border-border bg-muted/20'}"
  >
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-base font-semibold">
        {s.gate === 'proceed' ? '✅ PROCEED' : s.gate === 'pivot' ? '❌ PIVOT' : s.track === 'memory' ? '\U0001F9E0 Recall results' : 'ℹ️ Results'}
      </span>
      <span class="text-xs text-muted-foreground">legs: {s.modes.map(legLabel).join(' · ')}</span>
      <Badge variant="outline" class="font-mono">{s.elapsed_ms}ms</Badge>
      {#if !judged}<Badge variant="secondary">answers only &middot; judge off</Badge>{/if}
    </div>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {#if s.track === 'memory'}
        <span>Remembered turns: <span class="font-mono">{s.remembered_turns ?? 0}</span></span>
        <span>Recalled for: <span class="font-mono">{s.recalled_for ?? 0}/{s.total_questions}</span></span>
        <span>Possible stale leaks: <span class="font-mono {(s.stale_hits ?? 0) > 0 ? 'text-amber-600' : ''}">{s.stale_hits ?? 0}</span></span>
      {/if}
      {#if judged}
        <span>
          Passing (all {s.total_questions}):
          {#each s.modes as mode (mode)}<span class="ml-1 font-mono">{legLabel(mode)}={s.passing?.[mode] ?? 0}</span>{/each}
        </span>
        {#if s.track !== 'memory'}
          <span>
            On <code class="font-mono">requires_graph</code> ({s.requires_graph_total ?? 0}):
            {#each s.modes as mode (mode)}<span class="ml-1 font-mono">{legLabel(mode)}={s.requires_graph_passing?.[mode] ?? 0}</span>{/each}
          </span>
        {/if}
      {/if}
    </div>
    {#if !judged}
      <p class="text-xs text-muted-foreground">
        Judge was off &mdash; answers shown without marks. Enable &ldquo;Judge answers&rdquo; to grade
        each answer against the ideal answer.
      </p>
    {/if}
  </div>
{/snippet}

<!-- Per-category x leg passing counts (judge marks). -->
{#snippet categoryBreakdown(bc: Record<string, { total: number; pass: Record<string, number> }>, cols: string[])}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1.5 text-left">Category</th>
          {#each cols as mode (mode)}<th class="px-2 py-1.5 text-center">{legLabel(mode)}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each Object.entries(bc) as [cat, st] (cat)}
          {@const flatPass = st.pass?.flat ?? 0}
          <tr class="border-t">
            <td class="px-2 py-1.5">{cat}</td>
            {#each cols as mode (mode)}
              <td class="px-2 py-1.5 text-center font-mono tabular-nums {mode !== 'flat' && (st.pass?.[mode] ?? 0) > flatPass ? 'font-semibold text-emerald-600' : 'text-muted-foreground'}">
                {st.pass?.[mode] ?? 0}/{st.total}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}
