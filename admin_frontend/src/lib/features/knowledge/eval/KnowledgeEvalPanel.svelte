<!--
  L3 prototype (Phase 5e) — Eval Batch panel.

  Hosted on its own top-level Eval page (moved out of the Knowledge tabs). Three phases of UI:

    1. idle  → setup checkboxes (ingest synthetic / build graph) + Run button
    2. running → live progress table; rows append/update as
                 ``knowledge.eval.question_completed`` events arrive
    3. completed → final summary card with PROCEED/PIVOT gate verdict

  All transport plumbing lives in the controller (`knowledge-eval.svelte.ts`);
  this component is a thin view.
-->
<script lang="ts">
  import { onMount } from 'svelte';
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
  import { buildActivityLines } from '$lib/features/knowledge/eval/eval-activity';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import { preferenceTabHref } from '$lib/features/preferences/shared/preferences-tabs';
  import type { EvalQuestionItem } from '$lib/api/knowledge';
  import type { EvalCompletedPayload, RecalledFact } from '$lib/features/knowledge/shared/knowledge-events';
  import { getPreferences, type WorkspacePreferences } from '$lib/api/preferences';
  import {
    EVAL_ALL_LEGS,
    EVAL_LEG_LABEL,
    type KnowledgeEvalModel
  } from '$lib/features/knowledge/state/knowledge-eval.svelte';

  interface Props {
    /** Eval model (track state, run lifecycle, corpus picker) — created and
     *  init/torn-down by the host Eval page; this component is a pure view. */
    eval_: KnowledgeEvalModel;
  }

  let { eval_ }: Props = $props();

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

  onMount(() => {
    // Model lifecycle (subscribe + replay run state + corpus scan, then teardown)
    // is owned by the host Eval page. The panel just loads the read-only engine
    // params strip shown at the top.
    void loadPrefs();
  });

  // The shared knowledge SSE is paused while this browser tab is hidden (to free the
  // per-origin connection budget so other tabs don't stall). A run keeps progressing
  // server-side meanwhile, so on refocus we re-pull the authoritative run state to
  // backfill any events missed while backgrounded.
  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible') void eval_.resync();
  }

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

  // The live activity feed lines (built once here, shared with the terminal and the
  // collapsed Activity header). `currentActivityLine` is the latest line — shown in
  // the section header while collapsed so the feed still reports where it's at.
  const activityLines = $derived(
    buildActivityLines({
      setupEvents: eval_.setupEvents,
      rows: eval_.rows,
      status: eval_.status,
      totalQuestions: eval_.totalQuestions,
      summaryGate: eval_.summary?.gate ?? null,
      summaryElapsedMs: eval_.summary?.elapsed_ms ?? null,
      failureMessage: eval_.failureMessage
    })
  );
  const currentActivityLine = $derived(activityLines.at(-1)?.text.trim() ?? '');

  // Questions-card header summary: selection count out of the corpus total (no cap;
  // a non-empty selection is required to run).
  const questionsSummary = $derived(
    `${eval_.selectedCount}/${eval_.questions.length} selected${
      eval_.selectedCount === 0 ? ' · select at least one' : ''
    }`
  );
  const allSelected = $derived(
    eval_.questions.length > 0 && eval_.selectedCount === eval_.questions.length
  );

  // Engine params strip — the preference values that actually drive this run, per track.
  // The shared Graphiti graph engine (graph.*) governs memory recall AND the knowledge
  // graphiti leg, so those knobs are listed for both tracks; the flat (Qdrant hybrid)
  // retrieval knobs (knowledge.retrieval.*) are listed only for the knowledge track.
  // Reranker chips appear only when actually engaged (cross-encoder recipe / flat reranker
  // enabled). Mirrors Settings → Graph engine + Knowledge so the strip == what runs.
  type Param = { label: string; value: string };
  const TEMPORAL_LENS_LABEL: Record<'current' | 'all', string> = {
    current: 'current only',
    all: 'include historical'
  };
  const dash = (v: string | null | undefined) => (v && String(v).trim() ? String(v) : '—');
  const onOff = (b: boolean) => (b ? 'on' : 'off');
  const engineParams = $derived.by<Param[]>(() => {
    if (!prefs) return [];
    const g = prefs.graph;
    const a = prefs.knowledge.answering;

    // Models. Answer model (what the judge grades) drives both tracks; the Graphiti
    // small/sub-step model is surfaced on the memory tab per request.
    const models: Param[] = [
      { label: 'Graph backend', value: g.backend },
      { label: 'Extraction model', value: dash(g.extraction_model) }
    ];
    if (isMemory) models.push({ label: 'Small model', value: dash(g.small_model) });
    models.push({ label: 'Embedder', value: dash(g.embedder_model) });
    models.push({ label: 'Answer model', value: dash(a.model_resolved ?? a.model) });

    // Shared Graphiti graph-engine knobs (memory recall + knowledge graphiti leg).
    const graphEngine: Param[] = [
      ...models,
      { label: 'Temporal lens', value: TEMPORAL_LENS_LABEL[g.temporal_default] ?? g.temporal_default },
      { label: 'Expansion hops', value: String(g.k_hop) },
      { label: 'Search recipe', value: g.search_recipe },
      { label: 'Search scope', value: g.search_scope },
      { label: 'Candidate sim floor', value: String(g.sim_min_score) }
    ];
    // Fact reranker only kicks in on the cross-encoder recipe.
    if (g.search_recipe === 'cross_encoder') {
      graphEngine.push({ label: 'Graph reranker', value: dash(g.reranker.model_id) });
      graphEngine.push({ label: 'Rerank floor', value: String(g.reranker.min_relevance) });
    }
    graphEngine.push({ label: 'Graph observability', value: g.observability });

    if (isMemory) {
      return [...graphEngine, { label: 'Recall top-k', value: String(prefs.memory.search.top_k) }];
    }

    // Knowledge flat (Qdrant dense + BM25 hybrid) leg knobs.
    const r = prefs.knowledge.retrieval;
    const flat: Param[] = [
      { label: 'Retrieval top-k', value: String(r.top_k) },
      { label: 'Flat min score', value: String(r.min_score) },
      { label: 'Hybrid', value: onOff(r.hybrid) },
      { label: 'Prefetch', value: String(r.prefetch_limit) }
    ];
    if (r.reranker.enabled) {
      flat.push({ label: 'Flat reranker', value: dash(r.reranker.model_id) });
      flat.push({ label: 'Rerank top-n', value: String(r.reranker.top_n) });
    }
    return [...graphEngine, ...flat];
  });

  // Ingest-time knobs (knowledge chunking) — only relevant, and only shown, while
  // "Ingest corpus first" is checked (they shape the index build, not run-time recall).
  const ingestParams = $derived.by<Param[]>(() => {
    if (!prefs || isMemory || !eval_.ingestSynthetic) return [];
    const c = prefs.knowledge.chunking;
    return [
      { label: 'Chunk size', value: String(c.chunk_size) },
      { label: 'Chunk overlap', value: String(c.chunk_overlap) },
      { label: 'Structural ctx', value: onOff(c.embed_structural_context) }
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

  // Cost (LLM + reranker; embeddings unpriced). Questions cost accumulates live from rows;
  // ingest + grand total arrive with the summary (memory only — knowledge ingest is deferred).
  function fmtCost(v: number | null | undefined): string {
    const n = Number(v ?? 0);
    if (!Number.isFinite(n) || n <= 0) return '$0.00';
    return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
  }
  const questionsCost = $derived(eval_.rows.reduce((s, r) => s + (r.cost_usd || 0), 0));
  const ingestCost = $derived(eval_.summary?.ingest_cost_usd ?? null);
  const totalCost = $derived(eval_.summary?.total_cost_usd ?? questionsCost + (ingestCost ?? 0));

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
  // Full-width row colspan: #, Question, Ideal, <N legs>, [Δ], Links.
  const resultsColspan = $derived(3 + legColumns.length + (showDelta ? 1 : 0) + 1);

  // One-line settings summary for the collapsed Settings card header.
  const settingsSummary = $derived.by(() => {
    if (!prefs) return '';
    const g = prefs.graph;
    return `${g.backend} · ${g.search_recipe} · hops ${g.k_hop} · sim ${g.sim_min_score}`;
  });

</script>

<svelte:document onvisibilitychange={onVisibilityChange} />

<section class="grid gap-4">
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

  <!-- Engine settings that drive this run (read-only) — collapsed by default; the gear jumps
       to the Graph engine preferences and stays visible while collapsed. A one-line summary
       keeps the key knobs glanceable when collapsed. Sits under the run controls. -->
  {#if engineParams.length > 0}
    <KnowledgeCollapsibleSectionCard
      title="Settings"
      bodyId="knowledge-eval-settings"
      defaultExpanded={false}
      collapsedSummary={settingsSummary}
    >
      {#snippet headerActions()}
        <a
          href={preferenceTabHref('graph-engine', base)}
          class="inline-flex items-center gap-1 rounded border px-2 py-0.5 font-sans text-xs text-primary hover:bg-primary/5"
          title="Change these in the Graph engine settings"
        >
          <Settings2 size={12} aria-hidden="true" /> Settings
        </a>
      {/snippet}
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 font-sans text-xs">
        {#each engineParams as p (p.label)}
          <span class="text-muted-foreground">
            {p.label}: <span class="font-mono text-foreground">{p.value}</span>
          </span>
        {/each}
        {#if ingestParams.length > 0}
          <span
            class="font-semibold uppercase tracking-wide text-muted-foreground"
            title="Ingest-time settings — apply because “Ingest corpus first” is on"
          >· Ingest</span>
          {#each ingestParams as p (p.label)}
            <span class="text-muted-foreground">
              {p.label}: <span class="font-mono text-foreground">{p.value}</span>
            </span>
          {/each}
        {/if}
      </div>
    </KnowledgeCollapsibleSectionCard>
  {/if}

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
          disabled={allSelected || eval_.questions.length === 0 || isBusy}
          onclick={eval_.selectAll}
        >
          Select all
        </button>
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
      defaultExpanded={false}
      collapsedSummary={currentActivityLine}
    >
      <KnowledgeEvalTerminal lines={activityLines} />
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
      <!-- Total cost — accumulates live as questions land (LLM + reranker; embeddings unpriced).
           Knowledge ingest cost is deferred (multi-run), shown as “—”. -->
      {#if totalCost > 0 || isBusy}
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
          <span class="font-semibold uppercase tracking-wide text-muted-foreground">Cost</span>
          <span class="font-mono text-foreground">≈ {fmtCost(totalCost)}</span>
          <span class="text-muted-foreground">
            (ingest {isMemory ? fmtCost(ingestCost) : '—'} · Q {fmtCost(questionsCost)})
          </span>
          <span class="ml-auto text-[11px] text-muted-foreground">
            LLM + reranker · embeddings not priced
          </span>
        </div>
      {/if}
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
  <!-- No overflow wrapper: a scroll container would trap the sticky header. The thead pins to
       the page scroll, offset below the sticky page header + run-controls toolbar. -->
  <div class="rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead
        class="text-xs uppercase tracking-wide text-muted-foreground [&_th]:sticky [&_th]:top-[calc(4rem+var(--admin-page-header-h,0px)+var(--admin-page-sticky-toolbar-h,0px))] [&_th]:z-10 [&_th]:border-b [&_th]:bg-muted"
      >
        <tr>
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
                {#if r.subcategory}
                  <div class="flex flex-wrap items-center gap-2 font-sans text-xs">
                    <span class="text-muted-foreground">{r.subcategory}</span>
                  </div>
                {/if}
                <div class="grid gap-3 md:grid-cols-2">
                  {#each legColumns as mode (mode)}
                    {#if r.legs[mode]}
                      {@const leg = r.legs[mode]}
                      <div class="grid content-start gap-2 rounded-md border bg-background p-2.5">
                        <div class="flex flex-wrap items-center gap-2">
                          <span class="font-sans text-xs font-semibold">{legLabel(mode)}</span>
                          <Badge variant={markVariant(leg.mark)} class="font-mono">{leg.mark || '—'}</Badge>
                          <span class="font-mono text-xs tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
                          {#if leg.cost_usd}
                            <span class="font-mono text-xs tabular-nums text-muted-foreground">{fmtCost(leg.cost_usd)}</span>
                          {/if}
                        </div>
                        <!-- Compact judge line (the verdict mark is already in the header above). -->
                        {#if leg.reason}
                          <p class="text-xs leading-5 text-muted-foreground">
                            <span class="font-semibold text-foreground">Judge:</span> {leg.reason}
                          </p>
                        {/if}
                        {@render recalledTable(leg.recalled ?? [])}
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

<!-- Recalled facts as a table: fact text + temporal validity + relationship + status + score.
     Memory legs populate this; knowledge graphiti facts are pending the answer-path change. -->
{#snippet recalledTable(facts: RecalledFact[])}
  {#if facts.length === 0}
    <p class="text-xs italic text-muted-foreground">No recalled facts.</p>
  {:else}
    <div class="rounded-md border">
      <div class="border-b bg-muted/30 px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Recalled facts ({facts.length})
      </div>
      <div class="overflow-x-auto">
        <table class="w-full border-collapse font-sans text-xs">
          <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th class="px-2 py-1 text-left">Fact</th>
              <th class="px-2 py-1 text-left">Relationship</th>
              <th class="px-2 py-1 text-left">Valid from</th>
              <th class="px-2 py-1 text-left">Invalid at</th>
              <th class="px-2 py-1 text-left">Status</th>
              <th class="px-2 py-1 text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {#each facts as f, i (i)}
              <tr class="border-t align-top">
                <td class="max-w-[24rem] px-2 py-1">
                  <span>{f.fact || f.memory}</span>
                  {#if f.kind && f.kind !== 'fact'}
                    <span class="ml-1 text-[10px] uppercase text-muted-foreground">· {f.kind}</span>
                  {/if}
                </td>
                <td class="px-2 py-1 font-mono text-[11px] text-muted-foreground">{f.name || '—'}</td>
                <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.valid_at || '—'}</td>
                <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.invalid_at || '—'}</td>
                <td class="px-2 py-1">
                  {#if (f.kind ?? 'fact') === 'fact'}
                    {#if f.superseded}
                      <Badge variant="warning">superseded</Badge>
                    {:else}
                      <Badge variant="success">active</Badge>
                    {/if}
                  {:else}
                    <span class="text-muted-foreground">—</span>
                  {/if}
                </td>
                <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
                  {f.score != null ? f.score.toFixed(3) : '—'}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
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
        {s.gate === 'proceed' ? '✅ PROCEED' : s.gate === 'pivot' ? '❌ PIVOT' : s.track === 'memory' ? '🧠 Recall results' : 'ℹ️ Results'}
      </span>
      {#if s.track !== 'memory'}
        <span class="text-xs text-muted-foreground">legs: {s.modes.map(legLabel).join(' · ')}</span>
      {/if}
      <Badge variant="outline" class="font-mono">{s.elapsed_ms}ms</Badge>
      {#if (s.total_cost_usd ?? 0) > 0}
        <Badge variant="outline" class="font-mono" title="LLM + reranker; embeddings not priced">{fmtCost(s.total_cost_usd)}</Badge>
      {/if}
      {#if !judged}<Badge variant="secondary">answers only &middot; judge off</Badge>{/if}
    </div>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {#if s.track === 'memory'}
        <span>Recalled for: <span class="font-mono">{s.recalled_for ?? 0}/{s.total_questions}</span></span>
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
