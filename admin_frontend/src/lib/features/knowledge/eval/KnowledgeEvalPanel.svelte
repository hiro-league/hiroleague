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
  import { onMount, type Component, type Snippet } from 'svelte';
  import { base } from '$app/paths';
  import {
    Check,
    ChevronRight,
    Circle,
    CircleCheck,
    CircleDashed,
    CircleDot,
    CircleSlash,
    CircleX,
    Copy,
    Download,
    ExternalLink,
    FolderSearch,
    LoaderCircle,
    Microscope,
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
  import EvalCorpusReview from '$lib/features/knowledge/eval/EvalCorpusReview.svelte';
  import KnowledgeEvalRebuildConfirmDialog from '$lib/features/knowledge/eval/KnowledgeEvalRebuildConfirmDialog.svelte';
  import { buildActivityLines } from '$lib/features/knowledge/eval/eval-activity';
  import { formatEvalRowForAI } from '$lib/features/knowledge/eval/eval-clipboard';
  import type { EvalRow } from '$lib/features/knowledge/state/knowledge-eval.svelte';
  import GraphRunsRetrievalTraceDialog from '$lib/features/graph-runs/GraphRunsRetrievalTraceDialog.svelte';
  import GraphRunsIngestTraceDialog from '$lib/features/graph-runs/GraphRunsIngestTraceDialog.svelte';
  import {
    getGraphRunIngestTrace,
    getGraphRunRetrievalTrace,
    type IngestTraceRecord,
    type RetrievalTraceRecord
  } from '$lib/api/graph-runs';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import { preferenceTabHref } from '$lib/features/preferences/shared/preferences-tabs';
  import { exportEvalResultsLocomo, type EvalQuestionItem } from '$lib/api/knowledge';
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

  // The memory track is a single recall leg: no flat/graphiti legs, no Δ, no gate. Declared
  // up top because several derived values + helpers below branch on it.
  const isMemory = $derived(eval_.track === 'memory');

  // Label for the dialogs' optional "Corpus" tab (empty = no tab). Memory track with episodes
  // loaded; the count is shown so it reads as a real tab.
  const corpusTabLabel = $derived(
    isMemory && eval_.corpusEpisodes.length > 0 ? `Corpus (${eval_.corpusEpisodes.length})` : ''
  );

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

  // --- Question filters (free text + difficulty + saved state) -------------------------------
  // View-only filters over the checklist. "Select all" / "Clear selection" act on the *filtered*
  // set, so you can e.g. select only the failed questions, or only one difficulty. State filtering
  // is memory-only (knowledge has no saved per-question status).
  type QDifficulty = 'all' | 'medium' | 'hard' | 'very_hard' | 'unspecified';
  type QState = 'all' | 'pass' | 'partial' | 'fail' | 'abstain' | 'answered' | 'not_run';
  let qSearch = $state('');
  let qDifficulty = $state<QDifficulty>('all');
  let qState = $state<QState>('all');
  let qCategory = $state<string>('all');
  const qFiltered = $derived(
    qSearch.trim() !== '' || qDifficulty !== 'all' || qState !== 'all' || qCategory !== 'all'
  );
  function resetQuestionFilters() {
    qSearch = '';
    qDifficulty = 'all';
    qState = 'all';
    qCategory = 'all';
  }

  // Distinct categories (in first-seen order) for the category filter dropdown.
  const categoryOptions = $derived.by(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const q of eval_.questions) {
      const c = q.category || '';
      if (c && !seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
    return out;
  });

  // Match a question's saved status against the state filter. savedStatus → ✓/◐/✗/🛇 (judged),
  // '' (answered, judge off) or undefined (not run).
  function matchesState(id: string): boolean {
    if (qState === 'all') return true;
    const s = eval_.savedStatus(id);
    switch (qState) {
      case 'pass': return s === '✓';
      case 'partial': return s === '◐';
      case 'fail': return s === '✗';
      case 'abstain': return s === '🛇';
      case 'answered': return s === '';
      case 'not_run': return s === undefined;
      default: return true;
    }
  }

  const filteredQuestions = $derived.by(() => {
    const term = qSearch.trim().toLowerCase();
    return eval_.questions.filter((q) => {
      if (qCategory !== 'all' && (q.category || '') !== qCategory) return false;
      if (qDifficulty !== 'all') {
        const d = (q.difficulty || 'unspecified') as string;
        if ((d === '' ? 'unspecified' : d) !== qDifficulty) return false;
      }
      if (isMemory && !matchesState(q.id)) return false;
      if (term) {
        const hay = `${q.question} ${q.subcategory ?? ''} ${q.id} ${q.category}`.toLowerCase();
        if (!hay.includes(term)) return false;
      }
      return true;
    });
  });
  const filteredIds = $derived(filteredQuestions.map((q) => q.id));

  // Group the (filtered) question bank by category for the checklist.
  const groups = $derived.by(() => {
    const map = new Map<string, EvalQuestionItem[]>();
    for (const q of filteredQuestions) {
      const arr = map.get(q.category) ?? [];
      arr.push(q);
      map.set(q.category, arr);
    }
    return [...map.entries()];
  });

  function categoryAllSelected(items: EvalQuestionItem[]): boolean {
    return items.length > 0 && items.every((q) => eval_.isSelected(q.id));
  }


  // Difficulty buckets render as a fixed curve (easiest→hardest), not summary-dict order, so
  // the by-difficulty table reads top-to-bottom as a difficulty ramp.
  const DIFFICULTY_ORDER = ['medium', 'hard', 'very_hard', 'unspecified'];
  function orderedDifficulty(
    bd: Record<string, { total: number; pass: Record<string, number> }>
  ): Record<string, { total: number; pass: Record<string, number> }> {
    const rank = (k: string) => {
      const i = DIFFICULTY_ORDER.indexOf(k);
      return i === -1 ? DIFFICULTY_ORDER.length : i;
    };
    return Object.fromEntries(Object.entries(bd).sort((a, b) => rank(a[0]) - rank(b[0])));
  }

  // Difficulty chip shown next to each question in the picker. Returns null for
  // unspecified/empty so unlabeled corpora render no chip.
  function difficultyMeta(d: string): { label: string; cls: string } | null {
    switch (d) {
      case 'medium':
        return { label: 'medium', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300' };
      case 'hard':
        return { label: 'hard', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' };
      case 'very_hard':
        return { label: 'very hard', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300' };
      default:
        return null;
    }
  }

  // Saved-result coverage indicator for a question in the checklist (memory track only). A small
  // colored status icon (with a hover tooltip) — non-intrusive, sits after the question text — so
  // you can see at a glance what's been run and target the gaps when re-running a subset. Maps the
  // persisted judge mark, or its absence (``undefined`` ⇒ not run yet).
  function savedBadge(id: string): { Icon: Component; cls: string; title: string } | null {
    if (!isMemory) return null;
    const s = eval_.savedStatus(id);
    if (s === undefined)
      return { Icon: Circle, cls: 'text-muted-foreground/40', title: 'Not run yet' };
    switch (s) {
      case '✓':
        return { Icon: CircleCheck, cls: 'text-emerald-600 dark:text-emerald-400', title: 'Pass — saved answer matches the ideal' };
      case '◐':
        return { Icon: CircleDashed, cls: 'text-amber-600 dark:text-amber-400', title: 'Partial — partially correct or incomplete' };
      case '✗':
        return { Icon: CircleX, cls: 'text-rose-600 dark:text-rose-400', title: 'Fail — saved answer is wrong' };
      case '🛇':
        return { Icon: CircleSlash, cls: 'text-muted-foreground', title: 'Abstain — declined (correct for a negative-control question)' };
      default:
        // Answered, but judge was off (no mark) — it has a saved answer, just no grade.
        return { Icon: CircleDot, cls: 'text-sky-600 dark:text-sky-400', title: 'Answered — saved, but judge was off (no grade)' };
    }
  }

  // --- Corpus review (memory track) ---------------------------------------------------------
  // Episode timestamps are dated turns (fictional far-future dates); show the date only —
  // the time-of-day is noise for a review-at-a-glance. ISO slice keeps the UTC date stable.
  function fmtEpisodeDate(iso: string): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(0, 10);
  }

  // Corpus date span (first → last episode) for the stats header + collapsed summary.
  const corpusSpan = $derived.by(() => {
    const m = eval_.corpusMeta;
    if (!m || !m.first_timestamp) return '—';
    const a = fmtEpisodeDate(m.first_timestamp);
    const b = fmtEpisodeDate(m.last_timestamp);
    return a === b ? a : `${a} → ${b}`;
  });
  const corpusSummary = $derived(
    eval_.corpusEpisodes.length > 0 ? `${eval_.corpusEpisodes.length} episodes · ${corpusSpan}` : ''
  );

  // Ingested-episode readout for the Corpus header — which turns are in the graph. Stored spans
  // are 0-based inclusive; displayed +1 as 1-based episode numbers to match the "Episodes From..To"
  // box (so "11–30" in the box reads as "11–30" here). Gaps stay visible so a missed range shows.
  // "not ingested yet" until the first ingest batch lands; resets after a graph wipe.
  const ingestedLabel = $derived.by(() => {
    const ing = eval_.ingested;
    if (!ing || ing.count === 0) return 'not ingested yet';
    const spans = ing.ranges
      .map(([s, e]) => (s === e ? `${s + 1}` : `${s + 1}–${e + 1}`))
      .join(', ');
    const total = eval_.corpusMeta?.episode_count ?? 0;
    const totalStr = total > 0 ? `/${total}` : '';
    const batchStr = ing.batches > 1 ? ` · ${ing.batches} batches` : '';
    return `ingested ${spans} · ${ing.count}${totalStr} eps${batchStr}`;
  });
  // Header line for the Corpus card: episode stats + ingested progress.
  const corpusHeaderSummary = $derived(
    corpusSummary ? `${corpusSummary} · ${ingestedLabel}` : ingestedLabel
  );

  // Episode search lives on the Corpus stats line (panel-owned, bound into EvalCorpusReview).
  let corpusSearch = $state('');
  const corpusMatchCount = $derived.by(() => {
    const t = corpusSearch.trim().toLowerCase();
    if (!t) return eval_.corpusEpisodes.length;
    return eval_.corpusEpisodes.filter((ep) =>
      `${ep.body} ${ep.speaker} ${ep.id}`.toLowerCase().includes(t)
    ).length;
  });

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
    }${qFiltered ? ` · ${filteredQuestions.length} shown` : ''}${
      isMemory && eval_.savedCount > 0 ? ` · ${eval_.savedCount} saved` : ''
    }`
  );
  // "all selected" is over the FILTERED set (drives the Select-all button's disabled state).
  const allSelected = $derived(
    filteredQuestions.length > 0 && filteredQuestions.every((q) => eval_.isSelected(q.id))
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

  // Cost (LLM + reranker; embeddings unpriced). Questions cost accumulates live from rows;
  // ingest + grand total arrive with the summary (memory only — knowledge ingest is deferred).
  function fmtCost(v: number | null | undefined): string {
    const n = Number(v ?? 0);
    if (!Number.isFinite(n) || n <= 0) return '$0.00';
    return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
  }
  const questionsCost = $derived(eval_.rows.reduce((s, r) => s + (r.cost_usd || 0), 0));
  // CUMULATIVE per-corpus ingest spend (persisted in the ingested-ranges store; survives reload).
  // This is the source of truth when idle — the only place ingest cost lives across runs.
  const ingestCostCumulative = $derived(eval_.ingested?.cost_usd ?? 0);
  // Ingest (graph-build) cost also streams live: the memory runner emits a 'remember_done' setup
  // event carrying THIS batch's folded ingest cost the moment ingestion ends — before the terminal
  // summary and before the first question row — so the strip shows progress mid-run.
  const ingestCostLive = $derived.by(() => {
    for (let i = eval_.setupEvents.length - 1; i >= 0; i--) {
      const c = eval_.setupEvents[i].ingest_cost_usd;
      if (typeof c === 'number') return c;
    }
    return null;
  });
  // Displayed ingest cost: while a run is in flight, the persisted cumulative + this batch's live
  // cost (the batch isn't saved to the store until the run completes); once idle/reloaded, the
  // persisted cumulative is authoritative (loadResults refreshes it after each run).
  const ingestCost = $derived.by(() => {
    const running = eval_.status === 'starting' || eval_.status === 'running';
    if (running && ingestCostLive != null) return ingestCostCumulative + ingestCostLive;
    if (ingestCostCumulative > 0) return ingestCostCumulative;
    return eval_.summary?.ingest_cost_usd ?? ingestCostLive;
  });
  const totalCost = $derived((ingestCost ?? 0) + questionsCost);
  // "building…" only while ingestion is genuinely in flight: a remember phase has started but its
  // cost isn't known yet AND no question row exists yet (questions only run after remember). Once
  // rows stream — or the run isn't doing a rebuild — fall back to "—", never a stuck "building…".
  const ingestBuilding = $derived(
    isMemory &&
      ingestCost == null &&
      eval_.rows.length === 0 &&
      (eval_.status === 'starting' || eval_.status === 'running') &&
      eval_.setupEvents.some((e) => e.phase === 'remember')
  );

  const canRun = $derived(
    eval_.status === 'idle' ||
      eval_.status === 'completed' ||
      eval_.status === 'failed' ||
      eval_.status === 'cancelled'
  );
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Setup-only memory batch: Remember a range and/or Clear, with no questions selected — the
  // way a large corpus is built in monitored chunks before any recall. Lets Run fire with an
  // empty question selection (which is otherwise required).
  const setupOnlyMemory = $derived(isMemory && (eval_.ingestSynthetic || eval_.clearBefore));
  const runDisabled = $derived(
    !canRun || !eval_.selectedCorpus || (eval_.selectedCount === 0 && !setupOnlyMemory)
  );
  const runTitle = $derived(
    eval_.selectedCount === 0
      ? setupOnlyMemory
        ? 'Run a setup-only batch (remember / clear — no questions)'
        : 'Select at least one question'
      : 'Run the eval'
  );

  // Wipe guard: when the run will WIPE an existing graph — memory "Clear graph first", or the
  // knowledge "Rebuild graph" (which still wipes on ingest) — Run opens a confirm dialog first
  // (the wipe is destructive + costs money to rebuild). Nothing to wipe → run straight away.
  let confirmOpen = $state(false);
  function requestRun() {
    const wipes = isMemory ? eval_.clearBefore : eval_.rebuildChecked;
    if (wipes && eval_.selectedCorpusHasGraph) confirmOpen = true;
    else void eval_.start();
  }

  /** Color the mark chip. Negative-control abstain (🛇) reads as neutral, not green. */
  function markVariant(mark: string): 'success' | 'warning' | 'destructive' | 'secondary' {
    if (mark === '✓') return 'success';
    if (mark === '◐') return 'warning';
    if (mark === '✗') return 'destructive';
    return 'secondary'; // 🛇 abstain
  }

  /** Tooltip for the judge-mark glyph — the icons aren't self-explanatory (esp. the 🛇 abstain
   *  "stop sign"), so every mark badge carries this as its title. */
  function markTitle(mark: string): string {
    if (mark === '✓') return 'Pass — the answer matches the ideal';
    if (mark === '◐') return 'Partial — partially correct or incomplete';
    if (mark === '✗') return 'Fail — the answer is wrong';
    if (mark === '🛇') return 'Abstain — declined / “I don’t know” (the correct outcome for a negative-control question)';
    return 'Not judged (judge was off)';
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
  // Full-width row colspan: #, Question, Type, Difficulty, Ideal, <N legs>, [Δ].
  // (Trace/recall links moved out of the main row into the expanded fold.)
  const resultsColspan = $derived(5 + legColumns.length + (showDelta ? 1 : 0));

  // Graphiti retrieval trace — opens the SAME rich pipeline-trace dialog the Graph Runs page uses
  // (candidate→rank→temporal stage tables, with scores), loaded by the leg's ledger run_id. Only
  // graph legs have one (memory `recall`, knowledge `graphiti`); the flat leg has no graph search.
  let activeTrace = $state<RetrievalTraceRecord | null>(null);
  // Ideal + model answer for the trace's question, surfaced in the dialog header so recalled
  // facts can be read against what was expected / produced (set alongside `activeTrace`).
  let activeTraceIdeal = $state('');
  let activeTraceAnswer = $state('');
  let traceLoadingRunId = $state<string | null>(null);
  let traceError = $state<string | null>(null);
  const traceableLeg = (mode: string): boolean => mode === 'recall' || mode === 'graphiti';

  async function openTrace(runId: string, ideal = '', answer = '') {
    traceError = null;
    traceLoadingRunId = runId;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        // A recall is one fact search → one trace; take the latest if a run held several.
        activeTrace = traces[traces.length - 1];
        activeTraceIdeal = ideal;
        activeTraceAnswer = answer;
      } else {
        traceError = 'No retrieval trace recorded for this run (graph tracing may have been off).';
      }
    } catch (err) {
      traceError = err instanceof Error ? err.message : 'Failed to load retrieval trace.';
    } finally {
      traceLoadingRunId = null;
    }
  }

  // Ingest pipeline trace — the per-episode graph-build trace for the corpus's remember run.
  // Opened from the "Ingest pipeline" button when the run's ingest Graph Run id is known. Shows
  // the searchable source corpus as an extra tab (same as the retrieval trace).
  let activeIngestTrace = $state<IngestTraceRecord | null>(null);
  let ingestTraceLoading = $state(false);
  let ingestTraceError = $state<string | null>(null);
  async function openIngestTrace(runId: string) {
    ingestTraceError = null;
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        // The remember run ingests many episodes → many per-episode traces; open the first.
        // The Corpus tab shows the full (searchable) corpus regardless of which episode is shown.
        activeIngestTrace = traces[0];
      } else {
        ingestTraceError = 'No ingest trace recorded for this run (graph tracing may have been off).';
      }
    } catch (err) {
      ingestTraceError = err instanceof Error ? err.message : 'Failed to load ingest trace.';
    } finally {
      ingestTraceLoading = false;
    }
  }

  // Compact engine line for the "Copy for AI" brief — the few knobs that actually shape recall.
  const aiEngine = $derived.by(() => {
    if (!prefs) return '';
    const g = prefs.graph;
    const answer = prefs.knowledge.answering.model_resolved ?? prefs.knowledge.answering.model ?? '';
    return `${g.backend} · recipe=${g.search_recipe} · hops=${g.k_hop}${answer ? ` · answer=${answer}` : ''}`;
  });

  // Per-row "Copy for AI": build the Markdown brief (inline answers/judge/recalled + ledger-file
  // pointers) and write it to the clipboard. `copiedRow` flips the icon to a check briefly;
  // `copyError` surfaces a clipboard failure (e.g. denied permission) as a small banner.
  let copiedRow = $state<number | null>(null);
  let copyError = $state<string | null>(null);
  let exportingLocomo = $state(false);
  let locomoExportError = $state<string | null>(null);
  let locomoExportNotice = $state<string | null>(null);
  async function copyRowForAI(r: EvalRow) {
    copyError = null;
    try {
      const text = formatEvalRowForAI({
        row: r,
        legColumns,
        track: eval_.track,
        engine: aiEngine,
        corpus: eval_.selectedCorpus?.id ?? '',
        logDir: eval_.logDir
      });
      await navigator.clipboard.writeText(text);
      copiedRow = r.index;
      setTimeout(() => {
        if (copiedRow === r.index) copiedRow = null;
      }, 1500);
    } catch (err) {
      copyError = err instanceof Error ? err.message : 'Could not copy to clipboard.';
    }
  }

  async function exportLocomoResults() {
    const corpus = eval_.selectedCorpus;
    if (!corpus) return;
    exportingLocomo = true;
    locomoExportError = null;
    locomoExportNotice = null;
    try {
      const res = await exportEvalResultsLocomo(corpus.id, corpus.questions_path);
      const blob = new Blob([res.data.content], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      locomoExportNotice = `${res.data.exported_count}/${res.data.total_count} LoCoMo rows exported${
        res.data.partial ? ' (partial)' : ''
      }.`;
      setTimeout(() => {
        locomoExportNotice = null;
      }, 3500);
    } catch (err) {
      locomoExportError = err instanceof Error ? err.message : 'Could not export LoCoMo results.';
    } finally {
      exportingLocomo = false;
    }
  }

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
    <div class="flex flex-col gap-3">
      <!-- Row 1: corpus selection (folder + corpus) + run controls. Run is the primary
           action, so it stays on this line with the selection it acts on. -->
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

      <!-- Run controls — kept on the selection row; Run is the primary action. -->
      <div class="ml-auto flex gap-2">
        {#if eval_.rows.length > 0 || eval_.summary || eval_.failureMessage || (isMemory && eval_.savedCount > 0)}
          <Button
            variant="outline"
            disabled={isBusy}
            onclick={() => void eval_.clear()}
            title={isMemory
              ? 'Delete this corpus’s saved results from disk (ingested memory is kept)'
              : "Clear the last run's results"}
          >
            <Trash2 size={14} /> {isMemory ? 'Clear results' : 'Clear'}
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
        <Button disabled={runDisabled} onclick={requestRun} title={runTitle}>
          {#if isBusy}
            <LoaderCircle size={14} class="animate-spin" />
          {:else}
            <Play size={14} />
          {/if}
          {setupOnlyMemory && eval_.selectedCount === 0 ? 'Run batch' : 'Run eval'}
        </Button>
      </div>
      </div>

      <!-- Row 2: run options (ingest / legs / batch window / judge). -->
      <div class="flex flex-wrap items-center gap-3">
      <label
        class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm"
        title={isMemory
          ? 'Remember this episode range into the memory graph (APPENDS — does not wipe). Leave off to recall the existing graph (e.g. re-run a question subset).'
          : 'Wipe this corpus’s eval docs (chunks + graph), then re-ingest from scratch. Leave off to reuse the existing index.'}
      >
        <input type="checkbox" class="size-4" bind:checked={eval_.ingestSynthetic} disabled={isBusy} />
        <!-- Memory label aligned to the rest of the UI: these items are "episodes" everywhere
             else (corpus card, dropdown, batch window), and this mirrors the knowledge track's
             "Ingest corpus first". The old "Remember turns" used a word ("turns") found nowhere else. -->
        <span>{isMemory ? 'Ingest episodes first' : 'Ingest corpus first'}</span>
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
        <!-- Clear graph first — explicit, decoupled wipe. Off by default so batched remember
             APPENDS; check it only for a from-scratch rebuild (first batch). -->
        <label
          class="flex cursor-pointer select-none items-center gap-2 font-sans text-sm"
          title="Wipe this set’s memory graph BEFORE remembering. Use for a from-scratch rebuild (first batch only); leave OFF to append more episode batches to the existing graph."
        >
          <input type="checkbox" class="size-4" bind:checked={eval_.clearBefore} disabled={isBusy} />
          <span>Clear graph first</span>
        </label>
        <!-- Episode batch window — only meaningful while ingesting. 1-based, INCLUSIVE episode
             numbers (episode 1 = the first turn): ingest episodes From..To this run. To = 0 means
             "to the end". Build a large corpus in monitored chunks; the window auto-advances after
             each batch. (Controller converts to the backend's 0-based offset/count.) -->
        {#if eval_.ingestSynthetic}
          <div
            class="flex items-center gap-1.5 font-sans text-sm"
            title="Ingest episodes From..To this run (1-based, inclusive — episode 1 is the first turn). To = 0 means to the end. Auto-advances after each batch."
          >
            <span class="text-muted-foreground">Episodes</span>
            <input
              type="number"
              min="1"
              class="h-8 w-20 rounded-md border bg-background px-2 text-sm"
              value={eval_.episodeFrom}
              oninput={(e) => (eval_.episodeFrom = e.currentTarget.valueAsNumber)}
              disabled={isBusy}
              title="From episode (1-based, inclusive)"
            />
            <span class="text-muted-foreground">to</span>
            <input
              type="number"
              min="0"
              class="h-8 w-20 rounded-md border bg-background px-2 text-sm"
              value={eval_.episodeTo}
              oninput={(e) => (eval_.episodeTo = e.currentTarget.valueAsNumber)}
              disabled={isBusy}
              title="To episode (1-based, inclusive; 0 = to the end)"
            />
          </div>
        {/if}
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

  <!-- Corpus review (memory track) — a human-readable look at the turn corpus the questions
       probe: stats header (episode count / date span / question count + per-category breakdown)
       then the full episode transcript. Collapsed by default; sits above the questions. -->
  {#if isMemory && eval_.selectedCorpus}
    <KnowledgeCollapsibleSectionCard
      title="Corpus"
      bodyId="knowledge-eval-corpus"
      defaultExpanded={false}
      summary={corpusHeaderSummary}
    >
      {#snippet headerActions()}
        {#if eval_.corpusLoading}
          <LoaderCircle size={14} class="animate-spin text-muted-foreground" aria-hidden="true" />
        {/if}
      {/snippet}
      {#if eval_.corpusError}
        <p class="text-xs text-destructive">{eval_.corpusError}</p>
      {:else if eval_.corpusEpisodes.length === 0 && !eval_.corpusLoading}
        <p class="text-xs text-muted-foreground">No episodes loaded.</p>
      {:else}
        <!-- Top line: corpus stats + episode search (filters + highlights the transcript below). -->
        <div
          class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs"
        >
          <span class="text-muted-foreground">
            Episodes: <span class="font-mono text-foreground">{eval_.corpusMeta?.episode_count ?? 0}</span>
          </span>
          <span class="text-muted-foreground">
            Span: <span class="font-mono text-foreground">{corpusSpan}</span>
          </span>
          <span class="text-muted-foreground">
            Questions: <span class="font-mono text-foreground">{eval_.questions.length}</span>
          </span>
          <div class="ml-auto flex items-center gap-2">
            <input
              class="h-7 w-56 rounded-md border bg-background px-2 font-sans text-xs"
              placeholder="Search episodes…"
              bind:value={corpusSearch}
            />
            {#if corpusSearch.trim()}
              <span class="text-muted-foreground">{corpusMatchCount} of {eval_.corpusEpisodes.length} match</span>
              <button
                type="button"
                class="rounded border px-2 py-0.5 hover:bg-muted"
                onclick={() => (corpusSearch = '')}
              >
                Clear
              </button>
            {/if}
          </div>
        </div>
        <!-- Episode transcript with highlight; search owned by the stats line above. -->
        <EvalCorpusReview episodes={eval_.corpusEpisodes} bind:search={corpusSearch} showSearch={false} />
      {/if}
    </KnowledgeCollapsibleSectionCard>
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
        {#if eval_.questions.length > 0}
          <!-- Filters on the header line: search + category + difficulty + (memory) saved-state. -->
          <input
            class="h-7 w-40 rounded-md border bg-background px-2 font-sans text-xs"
            placeholder="Search questions…"
            bind:value={qSearch}
          />
          <select
            class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
            bind:value={qCategory}
            title="Filter by category"
          >
            <option value="all">All categories</option>
            {#each categoryOptions as c (c)}
              <option value={c}>{c}</option>
            {/each}
          </select>
          <select
            class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
            bind:value={qDifficulty}
            title="Filter by difficulty"
          >
            <option value="all">All difficulties</option>
            <option value="medium">medium</option>
            <option value="hard">hard</option>
            <option value="very_hard">very hard</option>
            <option value="unspecified">unspecified</option>
          </select>
          {#if isMemory}
            <select
              class="h-7 rounded-md border bg-background px-2 font-sans text-xs"
              bind:value={qState}
              title="Filter by saved result state"
            >
              <option value="all">All states</option>
              <option value="pass">Pass</option>
              <option value="partial">Partial</option>
              <option value="fail">Fail</option>
              <option value="abstain">Abstain</option>
              <option value="answered">Answered (no grade)</option>
              <option value="not_run">Not run</option>
            </select>
          {/if}
          {#if qFiltered}
            <button
              type="button"
              class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
              onclick={resetQuestionFilters}
              title="Clear all filters"
            >
              Reset
            </button>
          {/if}
        {/if}
        <!-- Select all / Clear act on the FILTERED set (so e.g. "select all failed" works). -->
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
          disabled={allSelected || filteredQuestions.length === 0 || isBusy}
          onclick={() => eval_.setCategorySelected(filteredIds, true)}
          title={qFiltered ? 'Select all questions matching the filters' : 'Select all questions'}
        >
          {qFiltered ? 'Select shown' : 'Select all'}
        </button>
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
          disabled={!filteredQuestions.some((q) => eval_.isSelected(q.id)) || isBusy}
          onclick={() => eval_.setCategorySelected(filteredIds, false)}
          title={qFiltered ? 'Deselect the questions matching the filters' : 'Clear the selection'}
        >
          {qFiltered ? 'Clear shown' : 'Clear selection'}
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
          {#if groups.length === 0}
            <p class="py-2 font-sans text-xs text-muted-foreground">No questions match the filters.</p>
          {/if}
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
                {#each items as q, qi (q.id)}
                  {@const dm = difficultyMeta(q.difficulty ?? '')}
                  <label class="flex cursor-pointer select-none items-start gap-2 py-0.5 font-sans text-sm">
                    <input
                      type="checkbox"
                      class="mt-0.5 size-3.5"
                      checked={eval_.isSelected(q.id)}
                      disabled={isBusy}
                      onchange={() => eval_.toggleQuestion(q.id)}
                    />
                    <!-- Per-category number (1..N within this category). -->
                    <span class="mt-px w-5 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">{qi + 1}.</span>
                    <span class="min-w-0">
                      {#if dm}
                        <span
                          class="mr-1 inline-block rounded px-1 py-px align-[1px] text-[10px] font-medium uppercase tracking-wide {dm.cls}"
                        >
                          {dm.label}
                        </span>
                      {/if}
                      {q.question}
                      {#if q.subcategory}
                        <span class="text-xs text-muted-foreground"> · {q.subcategory}</span>
                      {/if}
                      {#if savedBadge(q.id)}
                        {@const sb = savedBadge(q.id)}
                        {@const SavedIcon = sb?.Icon}
                        {#if SavedIcon}
                          <!-- Tooltip lives on a wrapping <span>: a `title` attr on the lucide
                               <svg> itself isn't shown as a hover tooltip by browsers. -->
                          <span
                            class="ml-1 inline-flex align-[-2px] {sb?.cls}"
                            title={sb?.title}
                            aria-label={sb?.title}
                            role="img"
                          >
                            <SavedIcon size={13} class="shrink-0" aria-hidden="true" />
                          </span>
                        {/if}
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

  <!-- Cost — its own strip (NOT nested in Results) so it shows during ingestion too: the memory
       remember/graph-build phase is the priciest part and runs before any question row exists, so
       a Results-gated cost box reported nothing while ingesting. Ingest cost streams in on the
       'remember_done' setup event; questions accumulate live; total folds both (LLM + reranker;
       embeddings unpriced). Knowledge ingest cost is deferred (multi-run), shown as “—”. -->
  {#if totalCost > 0 || isBusy}
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
      <span class="font-semibold uppercase tracking-wide text-muted-foreground">Cost</span>
      <span class="font-mono text-foreground">≈ {fmtCost(totalCost)}</span>
      <span class="text-muted-foreground" title="Ingest = cumulative graph-build spend for this corpus (sum of every ingest batch; survives reload). Q = this view's question cost.">
        (ingest{isMemory && ingestCostCumulative > 0 ? ' cumulative' : ''} {isMemory
          ? ingestCost != null
            ? fmtCost(ingestCost)
            : ingestBuilding
              ? 'building…'
              : '—'
          : '—'} · Q {fmtCost(questionsCost)})
      </span>
      {#if isMemory && eval_.ingestRunId}
        <!-- Open the corpus's graph-build (remember) pipeline trace; its Corpus tab shows the
             full source transcript, searchable. -->
        <button
          type="button"
          class="ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
          disabled={ingestTraceLoading}
          onclick={() => void openIngestTrace(eval_.ingestRunId!)}
          title="Open the ingest (graph-build) pipeline trace for this corpus"
        >
          {#if ingestTraceLoading}
            <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
          {:else}
            <Microscope size={10} aria-hidden="true" />
          {/if}
          Ingest pipeline
        </button>
        <span class="text-[11px] text-muted-foreground">LLM + reranker · embeddings not priced</span>
      {:else}
        <span class="ml-auto text-[11px] text-muted-foreground">
          LLM + reranker · embeddings not priced
        </span>
      {/if}
    </div>
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
      {#snippet headerActions()}
        {#if isMemory}
          <Button
            type="button"
            variant="outline"
            class="h-7"
            disabled={exportingLocomo || eval_.savedCount === 0 || !eval_.selectedCorpus}
            onclick={() => void exportLocomoResults()}
            title="Download saved memory results as a LoCoMo-compatible QA JSON file"
          >
            {#if exportingLocomo}
              <LoaderCircle size={14} class="animate-spin" />
            {:else}
              <Download size={14} />
            {/if}
            Export to LoCoMo
          </Button>
        {/if}
      {/snippet}
      {#if eval_.rows.length > 0 || eval_.status === 'running'}
        {@render resultsTable()}
      {/if}
      {#if eval_.summary}
        {@render summaryCard(eval_.summary)}
      {/if}
      {#if eval_.summary?.by_category && Object.keys(eval_.summary.by_category).length > 0}
        <p class="mb-1 mt-3 font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Results by category
        </p>
        {@render breakdownTable(eval_.summary.by_category, eval_.summary.modes, 'Category')}
      {/if}
      {#if eval_.summary?.by_difficulty && Object.keys(eval_.summary.by_difficulty).length > 0}
        <p class="mb-1 mt-3 font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Results by difficulty
        </p>
        {@render breakdownTable(
          orderedDifficulty(eval_.summary.by_difficulty),
          eval_.summary.modes,
          'Difficulty'
        )}
      {/if}
    </KnowledgeCollapsibleSectionCard>
  {/if}
</section>

<!-- Graphiti retrieval trace dialog — reuses the Graph Runs pipeline-trace viewer (per-stage
     candidate→rank→temporal tables with scores), opened by a leg's recall run_id. -->
{#if traceError}
  <div
    class="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive"
    role="alert"
  >
    {traceError}
  </div>
{/if}
{#if copyError}
  <div
    class="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive"
    role="alert"
  >
    Copy for AI failed: {copyError}
  </div>
{/if}
{#if locomoExportError}
  <div
    class="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive"
    role="alert"
  >
    LoCoMo export failed: {locomoExportError}
  </div>
{/if}
{#if locomoExportNotice}
  <div
    class="mt-2 rounded-md border border-primary/30 bg-primary/10 px-3 py-2 font-sans text-sm text-primary"
    role="status"
  >
    {locomoExportNotice}
  </div>
{/if}
{#if ingestTraceError}
  <div
    class="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive"
    role="alert"
  >
    {ingestTraceError}
  </div>
{/if}
<!-- Shared corpus tab content for both trace dialogs (memory track): the searchable source
     transcript, so a recalled/ingested fact can be traced back to its episode in-context. -->
{#snippet corpusTab()}
  <EvalCorpusReview episodes={eval_.corpusEpisodes} compact />
{/snippet}
<GraphRunsRetrievalTraceDialog
  trace={activeTrace}
  idealAnswer={activeTraceIdeal}
  llmAnswer={activeTraceAnswer}
  onClose={() => (activeTrace = null)}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTab : undefined}
/>
<!-- Ingest (graph-build) pipeline trace — opened from the Cost strip's "Ingest pipeline" button;
     same Corpus tab so the source transcript is reachable while inspecting the build. -->
<GraphRunsIngestTraceDialog
  trace={activeIngestTrace}
  onClose={() => (activeIngestTrace = null)}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTab : undefined}
/>

<!-- Rebuild-graph wipe confirm — gates Run when "Rebuild graph" is checked on a graphed corpus. -->
<KnowledgeEvalRebuildConfirmDialog
  bind:open={confirmOpen}
  track={eval_.track}
  corpusName={eval_.selectedCorpus?.name ?? ''}
  onConfirm={() => {
    confirmOpen = false;
    void eval_.start();
  }}
/>

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
          <th class="px-2 py-1.5 text-left">Type</th>
          <th class="px-2 py-1.5 text-left">Difficulty</th>
          <th class="px-2 py-1.5 text-left">Ideal</th>
          {#each legColumns as mode (mode)}
            <th class="px-2 py-1.5 text-left">{legLabel(mode)} answer</th>
          {/each}
          {#if showDelta}<th class="px-2 py-1.5 text-center" title="best graph leg vs flat">&#916;</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each eval_.rows as r (r.id)}
          <tr class="border-t align-top">
            <td class="px-2 py-1.5 font-mono tabular-nums text-xs text-muted-foreground">{r.index + 1}/{r.total}</td>
            <td class="px-2 py-1.5">
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
                <span class="line-clamp-2" title={r.question}>{r.question}</span>
              </button>
            </td>
            <!-- Type = the question's category (e.g. direct_recall, temporal). -->
            <td class="px-2 py-1.5 text-xs text-muted-foreground">{r.category || '—'}</td>
            <!-- Difficulty chip (authored medium/hard/very_hard); blank corpora show a dash. -->
            <td class="px-2 py-1.5">
              {#if difficultyMeta(r.difficulty)}
                {@const dm = difficultyMeta(r.difficulty)}
                <span
                  class="inline-block rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide {dm?.cls}"
                >
                  {dm?.label}
                </span>
              {:else}
                <span class="text-xs text-muted-foreground">—</span>
              {/if}
            </td>
            <td class="px-2 py-1.5 text-xs text-muted-foreground">
              <span class="line-clamp-2" title={r.gold || ''}>{r.gold || '—'}</span>
            </td>
            {#each legColumns as mode (mode)}
              <td class="px-2 py-1.5">
                {#if r.legs[mode]}
                  {@const leg = r.legs[mode]}
                  <div class="flex items-start gap-1.5">
                    <Badge variant={markVariant(leg.mark)} class="mt-0.5 font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
                    <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{leg.answer || '— (no answer)'}</span>
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
          </tr>
          <!-- Fold: per-leg judge verdict + recalled facts (expanded). Question/ideal/answer are
               already in the row above, so we don't repeat them here — only the diagnostic detail. -->
          <tr class="border-t bg-muted/10" hidden={!expandedRows.has(r.index)}>
            <td colspan={resultsColspan} class="px-3 py-3">
              <!-- Single column for the memory recall leg (full width); side-by-side only when
                   there are multiple legs to compare (knowledge flat vs graphiti). -->
              <div class="grid gap-4 {legColumns.length > 1 ? 'md:grid-cols-2' : ''}">
                {#each legColumns as mode, legIdx (mode)}
                  {#if r.legs[mode]}
                    {@const leg = r.legs[mode]}
                    <div class="grid content-start gap-2">
                      <!-- First line: leg meta (left) · actions trace / recall / copy (right). -->
                      <div class="flex flex-wrap items-center justify-between gap-2">
                        <div class="flex flex-wrap items-center gap-2">
                          <span class="font-sans text-xs font-semibold">{legLabel(mode)}</span>
                          <Badge variant={markVariant(leg.mark)} class="font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
                          <span class="font-mono text-xs tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
                          {#if leg.cost_usd}
                            <span class="font-mono text-xs tabular-nums text-muted-foreground">{fmtCost(leg.cost_usd)}</span>
                          {/if}
                          {#if r.subcategory && legIdx === 0}
                            <span class="font-sans text-xs text-muted-foreground">· {r.subcategory}</span>
                          {/if}
                        </div>
                        <div class="flex flex-wrap items-center gap-1">
                          {#if traceableLeg(mode) && leg.run_id}
                            <!-- Retrieval pipeline trace (per-stage candidate→rank→temporal). -->
                            <button
                              type="button"
                              class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
                              disabled={traceLoadingRunId !== null}
                              onclick={() => void openTrace(leg.run_id!, r.gold, leg.answer)}
                              title="Open the retrieval pipeline trace"
                            >
                              {#if traceLoadingRunId === leg.run_id}
                                <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
                              {:else}
                                <Microscope size={10} aria-hidden="true" />
                              {/if}
                              trace
                            </button>
                          {/if}
                          {#if leg.run_id}
                            <!-- Graph Run drill-in (labelled by leg: recall / graphiti / flat). -->
                            <a
                              class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                              href={graphRunPageUrl(leg.run_id)}
                              title="{legLabel(mode)} Graph Run"
                            >
                              <ExternalLink size={10} aria-hidden="true" />{mode}
                            </a>
                          {/if}
                          {#if legIdx === 0}
                            <!-- Copy-for-AI brief (per row; shown once, on the first leg). -->
                            <button
                              type="button"
                              class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                              onclick={() => void copyRowForAI(r)}
                              title="Copy a Markdown brief (answer + judge + recalled facts inline, ledger-file pointers for the full traces) to paste into your AI agent"
                            >
                              {#if copiedRow === r.index}
                                <Check size={10} aria-hidden="true" /> Copied
                              {:else}
                                <Copy size={10} aria-hidden="true" /> Copy
                              {/if}
                            </button>
                          {/if}
                        </div>
                      </div>
                      <!-- Judge verdict — its own line, above the recalled-memory sections. -->
                      {#if leg.reason}
                        <p class="rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5 text-xs leading-5 text-muted-foreground">
                          <span class="font-semibold text-foreground">Judge:</span> {leg.reason}
                        </p>
                      {/if}
                      <!-- Recalled memories: separate collapsible Facts / Entities / Episodes. -->
                      {@render recalledTable(leg.recalled ?? [])}
                    </div>
                  {/if}
                {/each}
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

<!-- Recalled items, split by kind into Facts / Entities / Episodes — each kind gets only the
     columns that apply (facts have temporal validity + relationship + status; entities have a
     type; episodes a turn timestamp), so non-fact rows stop rendering mostly-empty fact columns.
     Stacked (not tabbed): counts are small and review reads better without a click to reveal. -->
{#snippet recalledTable(items: RecalledFact[])}
  {@const facts = items.filter((r) => (r.kind ?? 'fact') === 'fact')}
  {@const entities = items.filter((r) => r.kind === 'entity')}
  {@const episodes = items.filter((r) => r.kind === 'episode')}
  {#if items.length === 0}
    <p class="text-xs italic text-muted-foreground">No recalled memories.</p>
  {:else}
    <div class="grid gap-2.5">
      {#if facts.length > 0}{@render factsTable(facts)}{/if}
      {#if entities.length > 0}{@render entitiesTable(entities)}{/if}
      {#if episodes.length > 0}{@render episodesTable(episodes)}{/if}
    </div>
  {/if}
{/snippet}

<!-- Reusable collapsible section: a <details> with a COLOR-CODED summary header (so Facts /
     Entities / Episodes are visually distinct and clearly separated) wrapping a scrollable table.
     Open by default; the disclosure triangle signals it collapses. ``headerCls`` is the per-kind
     color. -->
{#snippet recalledSection(title: string, count: number, headerCls: string, body: Snippet)}
  <details open class="overflow-hidden rounded-md border">
    <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide {headerCls}">
      {title} ({count})
    </summary>
    <div class="overflow-x-auto border-t">
      <table class="w-full border-collapse font-sans text-xs">
        {@render body()}
      </table>
    </div>
  </details>
{/snippet}

{#snippet factsTable(facts: RecalledFact[])}
  {#snippet body()}
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
            <span class="line-clamp-3" title={f.fact || f.memory}>{f.fact || f.memory}</span>
          </td>
          <td class="px-2 py-1 font-mono text-[11px] text-muted-foreground">{f.name || '—'}</td>
          <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.valid_at || '—'}</td>
          <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.invalid_at || '—'}</td>
          <td class="px-2 py-1">
            {#if f.superseded}
              <Badge variant="warning">superseded</Badge>
            {:else}
              <Badge variant="success">active</Badge>
            {/if}
          </td>
          <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
            {f.score != null ? f.score.toFixed(3) : '—'}
          </td>
        </tr>
      {/each}
    </tbody>
  {/snippet}
  {@render recalledSection('Recalled facts', facts.length, 'bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-200', body)}
{/snippet}

{#snippet entitiesTable(entities: RecalledFact[])}
  {#snippet body()}
    <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
      <tr>
        <th class="px-2 py-1 text-left">Entity</th>
        <th class="px-2 py-1 text-left">Type</th>
        <th class="px-2 py-1 text-right">Score</th>
      </tr>
    </thead>
    <tbody>
      {#each entities as e, i (i)}
        <tr class="border-t align-top">
          <td class="max-w-[28rem] px-2 py-1">
            <!-- Entity name (bold) over its attribute summary; both clamped with full text on hover. -->
            {#if e.name}<span class="font-semibold">{e.name}</span>{/if}
            <span class="line-clamp-2 text-muted-foreground" title={e.summary || e.memory}>{e.summary || e.memory}</span>
          </td>
          <td class="px-2 py-1">
            {#if e.entity_type}<Badge variant="outline" class="font-sans normal-case">{e.entity_type}</Badge>{:else}<span class="text-muted-foreground">—</span>{/if}
          </td>
          <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
            {e.score != null ? e.score.toFixed(3) : '—'}
          </td>
        </tr>
      {/each}
    </tbody>
  {/snippet}
  {@render recalledSection('Recalled entities', entities.length, 'bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-200', body)}
{/snippet}

{#snippet episodesTable(episodes: RecalledFact[])}
  {#snippet body()}
    <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
      <tr>
        <th class="px-2 py-1 text-left">Episode</th>
        <th class="px-2 py-1 text-left">When</th>
        <th class="px-2 py-1 text-right">Score</th>
      </tr>
    </thead>
    <tbody>
      {#each episodes as ep, i (i)}
        <tr class="border-t align-top">
          <td class="max-w-[32rem] px-2 py-1">
            <span class="line-clamp-3" title={ep.memory}>{ep.memory}</span>
          </td>
          <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{ep.valid_at ? fmtEpisodeDate(ep.valid_at) : '—'}</td>
          <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
            {ep.score != null ? ep.score.toFixed(3) : '—'}
          </td>
        </tr>
      {/each}
    </tbody>
  {/snippet}
  {@render recalledSection('Recalled episodes', episodes.length, 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200', body)}
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

<!-- Per-bucket x leg passing counts (judge marks). ``header`` labels the first column
     (Category or Difficulty); ``cols`` are the legs. -->
{#snippet breakdownTable(
  bc: Record<string, { total: number; pass: Record<string, number> }>,
  cols: string[],
  header: string
)}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1.5 text-left">{header}</th>
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
