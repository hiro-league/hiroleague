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
  import { goto } from '$app/navigation';
  import { seedGraphEpisodeFocus } from '$lib/features/knowledge/graph/knowledge-graph-prefs';
  import { base } from '$app/paths';
  import {
    Check,
    ChevronDown,
    ChevronRight,
    ChevronUp,
    ChevronsDownUp,
    ChevronsUpDown,
    Circle,
    CircleCheck,
    CircleDashed,
    CircleDot,
    CircleSlash,
    CircleX,
    Copy,
    Download,
    ExternalLink,
    Flag,
    FolderSearch,
    LoaderCircle,
    Microscope,
    Play,
    RefreshCw,
    Settings2,
    Square,
    Trash2,
    X
  } from '@lucide/svelte';
  import AdminSubtabStrip from '$lib/components/page/AdminSubtabStrip.svelte';
  import type { AdminSubtabDescriptor } from '$lib/components/page/tab-types';
  import { ADMIN_SHELL_STICKY_BLEED } from '$lib/styling/admin-tokens';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import KnowledgeEvalTerminal from '$lib/features/knowledge/eval/KnowledgeEvalTerminal.svelte';
  import EvalCorpusReview from '$lib/features/knowledge/eval/EvalCorpusReview.svelte';
  import KnowledgeEvalRebuildConfirmDialog from '$lib/features/knowledge/eval/KnowledgeEvalRebuildConfirmDialog.svelte';
  import KnowledgeEvalClearResultsConfirmDialog from '$lib/features/knowledge/eval/KnowledgeEvalClearResultsConfirmDialog.svelte';
  import { activityHeaderLine, buildActivityLines } from '$lib/features/knowledge/eval/eval-activity';
  import { highlightSegments } from '$lib/features/knowledge/eval/eval-highlight';
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
  import type {
    EvalCategoryStat,
    EvalCompletedPayload,
    EvidenceRecall,
    RecalledFact
  } from '$lib/features/knowledge/shared/knowledge-events';
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

  // --- Sticky sub-tabs (Control / Corpus / Questions / Answer Details / Report) ---------------
  // Section navigation as sticky underline sub-tabs under the run-controls toolbar. Local state
  // (not URL/session) — inner navigation, per the admin sub-tab pattern. Default to Control
  // (the run setup overview — requested over Questions on page load/refresh); the validity
  // effect snaps back if the active tab disappears (e.g. Corpus is memory-only and vanishes on
  // the knowledge track). Control holds the run options + read-only settings; Report (last tab)
  // holds the aggregate breakdown tables.
  type EvalSubtab = 'execute' | 'corpus' | 'questions' | 'answers' | 'report';
  let activeSubtab = $state<EvalSubtab>('execute');
  const subtabs = $derived<AdminSubtabDescriptor<EvalSubtab>[]>([
    { id: 'execute', label: 'Execute' },
    ...(isMemory ? [{ id: 'corpus' as const, label: 'Corpus' }] : []),
    { id: 'questions', label: 'Questions' },
    { id: 'answers', label: 'Answer Details' },
    { id: 'report', label: 'Report' }
  ]);
  $effect(() => {
    if (!subtabs.some((t) => t.id === activeSubtab)) activeSubtab = 'execute';
  });

  // Sticky sub-tab bar element — its height is published as a CSS var so the Results table's
  // sticky thead can offset beneath it (mirrors AdminPageStickyToolbar's own var).
  let subtabsEl = $state<HTMLDivElement | null>(null);

  onMount(() => {
    // Model lifecycle (subscribe + replay run state + corpus scan, then teardown)
    // is owned by the host Eval page. The panel just loads the read-only engine
    // params strip shown at the top.
    void loadPrefs();

    // Publish the sub-tab bar height so the results table's sticky thead aligns below it.
    const section = subtabsEl?.closest('section') ?? null;
    let published = -1;
    const publish = () => {
      if (!subtabsEl || !section) return;
      const h = Math.round(subtabsEl.getBoundingClientRect().height);
      if (h !== published) {
        published = h;
        section.style.setProperty('--admin-eval-subtabs-h', `${h}px`);
      }
    };
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publish) : null;
    if (subtabsEl && ro) ro.observe(subtabsEl);
    publish();

    return () => {
      ro?.disconnect();
      section?.style.removeProperty('--admin-eval-subtabs-h');
    };
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

  // Stable 1-based question number = the question's position in the full bank (independent of the
  // active filter), shown in the "#" column of the Questions table.
  const questionNumber = $derived.by(() => {
    const m = new Map<string, number>();
    eval_.questions.forEach((q, i) => m.set(q.id, i + 1));
    return m;
  });

  // Short name for the saved answering state (memory track), paired with savedBadge's icon/tooltip
  // in the Questions table's State column. '' / undefined ⇒ answered-without-grade / not-run.
  function savedStateName(id: string): string {
    if (!isMemory) return '';
    const s = eval_.savedStatus(id);
    if (s === undefined) return 'Not run';
    switch (s) {
      case '✓': return 'Pass';
      case '◐': return 'Partial';
      case '✗': return 'Fail';
      case '🛇': return 'Abstain';
      default: return 'Answered';
    }
  }

  // Column count for the Questions table's full-width rows. Knowledge: select + type + # +
  // question + difficulty + time = 6. Memory adds State + the recall-sufficiency flag = 8.
  const qColspan = $derived(isMemory ? 8 : 6);

  // --- Questions table sorting ----------------------------------------------------------------
  type QSortKey = 'category' | 'state' | 'recall' | 'number' | 'question' | 'difficulty' | 'time';
  let qSortKey = $state<QSortKey>('number');
  let qSortDir = $state<'asc' | 'desc'>('asc');
  function toggleSort(key: QSortKey) {
    if (qSortKey === key) qSortDir = qSortDir === 'asc' ? 'desc' : 'asc';
    else {
      qSortKey = key;
      qSortDir = 'asc';
    }
  }
  // Difficulty ramp + saved-state order used as sort keys (lower sorts first ascending).
  const _DIFF_SORT: Record<string, number> = { medium: 0, hard: 1, very_hard: 2 };
  const _STATE_SORT: Record<string, number> = { '✓': 0, '◐': 1, '✗': 2, '🛇': 3, '': 4 };
  function stateRank(id: string): number {
    const s = eval_.savedStatus(id);
    return s === undefined ? 5 : (_STATE_SORT[s] ?? 4);
  }
  // Recall-sufficiency sort: misses first (0), sufficient (1), unknown/not-judged last (2).
  function recallRank(id: string): number {
    const s = eval_.savedRecallSufficient(id);
    return s === undefined ? 2 : s ? 1 : 0;
  }
  // Sorted view of the filtered questions. Sorting changes ONLY display order, not membership,
  // so the Select/Clear-shown buttons (which act on `filteredIds`) are unaffected.
  const sortedQuestions = $derived.by(() => {
    const dir = qSortDir === 'asc' ? 1 : -1;
    const num = (q: EvalQuestionItem) => questionNumber.get(q.id) ?? 0;
    const cmp = (a: EvalQuestionItem, b: EvalQuestionItem): number => {
      switch (qSortKey) {
        case 'category':
          return (a.category || '').localeCompare(b.category || '') || num(a) - num(b);
        case 'question':
          return a.question.localeCompare(b.question);
        case 'difficulty':
          return (
            (_DIFF_SORT[a.difficulty || ''] ?? 3) - (_DIFF_SORT[b.difficulty || ''] ?? 3) ||
            num(a) - num(b)
          );
        case 'state':
          return stateRank(a.id) - stateRank(b.id) || num(a) - num(b);
        case 'recall':
          return recallRank(a.id) - recallRank(b.id) || num(a) - num(b);
        case 'time':
          return timeMs(eval_.savedAnsweredAt(a.id)) - timeMs(eval_.savedAnsweredAt(b.id)) || num(a) - num(b);
        default:
          return num(a) - num(b);
      }
    };
    return [...filteredQuestions].sort((a, b) => dir * cmp(a, b));
  });

  // Questions controls line (sticky filters/buttons bar) — measure its height so the table's
  // sticky head can pin directly beneath it. Conditionally mounted (only on the Questions tab),
  // so an $effect (re)observes whenever the bound element appears/disappears.
  let qControlsEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    const el = qControlsEl;
    if (!el) return;
    const section = el.closest('section');
    if (!section) return;
    const publish = () =>
      section.style.setProperty(
        '--admin-eval-qcontrols-h',
        `${Math.round(el.getBoundingClientRect().height)}px`
      );
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publish) : null;
    ro?.observe(el);
    // Republish on scroll too: it's the only moment the offset matters, and it self-heals if a
    // reflow (e.g. the toolbar collapsing on pin, which rewraps this bar) outpaces the observer.
    window.addEventListener('scroll', publish, { passive: true });
    publish();
    return () => {
      ro?.disconnect();
      window.removeEventListener('scroll', publish);
      section.style.removeProperty('--admin-eval-qcontrols-h');
    };
  });

  // Answer Details controls line (sticky filters/search bar) — same measure-and-publish pattern as
  // the Questions bar, so the results table's sticky thead can pin directly beneath it. Conditionally
  // mounted (only on the Answers tab), so the $effect (re)observes when the bound element appears.
  let aControlsEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    const el = aControlsEl;
    if (!el) return;
    const section = el.closest('section');
    if (!section) return;
    const publish = () =>
      section.style.setProperty(
        '--admin-eval-acontrols-h',
        `${Math.round(el.getBoundingClientRect().height)}px`
      );
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publish) : null;
    ro?.observe(el);
    window.addEventListener('scroll', publish, { passive: true });
    publish();
    return () => {
      ro?.disconnect();
      window.removeEventListener('scroll', publish);
      section.style.removeProperty('--admin-eval-acontrols-h');
    };
  });


  // Difficulty buckets render as a fixed curve (easiest→hardest), not summary-dict order, so
  // the by-difficulty table reads top-to-bottom as a difficulty ramp.
  const DIFFICULTY_ORDER = ['medium', 'hard', 'very_hard', 'unspecified'];
  function orderedDifficulty(
    bd: Record<string, EvalCategoryStat>
  ): Record<string, EvalCategoryStat> {
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

  // Episode search — owned by the panel, bound into EvalCorpusReview (which renders the input on
  // its sticky toolbar and shows its own match count).
  let corpusSearch = $state('');

  // The live activity feed lines (built once here, shared with the terminal and the
  // collapsed Activity header). `currentActivityLine` is the latest line — shown in
  // the section header while collapsed so the feed still reports where it's at.
  const activityInput = $derived({
    setupEvents: eval_.setupEvents,
    rows: eval_.rows,
    status: eval_.status,
    totalQuestions: eval_.totalQuestions,
    summaryGate: eval_.summary?.gate ?? null,
    summaryElapsedMs: eval_.summary?.elapsed_ms ?? null,
    failureMessage: eval_.failureMessage
  });
  const activityLines = $derived(buildActivityLines(activityInput));
  // Collapsed Activity header = the live current line (current episode during ingest, current
  // question during the Q phase), not the rolled-up "X/Y questions" counter.
  const currentActivityLine = $derived(activityHeaderLine(activityInput));

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

  // One model's tuning-profile params, compact (e.g. "temp 0.2 · max 1600 · think low"). Empty
  // string when the model has no tuning profile (embedders) or the profile id isn't found.
  function tuningChips(profileId: string | undefined): string {
    const p = profileId ? prefs?.tuning_profiles?.[profileId] : undefined;
    if (!p) return '';
    const bits = [`temp ${p.temperature}`, `max ${p.max_tokens}`];
    if (p.thinking) bits.push(`think ${p.thinking}`);
    return bits.join(' · ');
  }

  // Settings, organised for the (non-collapsible) Control tab:
  //  • MODELS — one line per model with its id + tuning-profile params (graph backend dropped:
  //    it's the standard now). Embedder has no tuning profile.
  //  • INGESTION knobs — knowledge chunking (only while "Ingest corpus first" is on).
  //  • ANSWER & RECALL knobs — retrieval + answering at question time.
  // Model lines (id + tuning-profile params), tagged by which Settings column they belong to:
  // ingestion models build the graph (extraction/small/embedder); the answer model drives recall.
  type ModelLine = { label: string; model: string; tuning: string; group: 'ingest' | 'recall' };
  const modelLines = $derived.by<ModelLine[]>(() => {
    if (!prefs) return [];
    const g = prefs.graph;
    const a = prefs.knowledge.answering;
    const out: ModelLine[] = [
      { label: 'Extraction', model: dash(g.extraction_model), tuning: tuningChips(g.extraction_tuning_profile), group: 'ingest' }
    ];
    if (isMemory)
      out.push({ label: 'Small', model: dash(g.small_model), tuning: tuningChips(g.small_tuning_profile), group: 'ingest' });
    out.push({ label: 'Embedder', model: dash(g.embedder_model), tuning: '', group: 'ingest' });
    // Answer + judge now use SEPARATE eval models/tuning (graph.eval.answer_* / judge_*), each
    // falling back to the knowledge answering model when unset. Memory answers with the eval
    // answer model; the knowledge track answers with the production answering pipeline, so its
    // Answer line shows that. The judge model grades both tracks.
    const answering = a.model_resolved ?? a.model;
    const ev = g.eval;
    out.push({
      label: 'Answer',
      model: dash(isMemory ? ev.answer_model || answering : answering),
      tuning: tuningChips(isMemory ? ev.answer_tuning_profile : prefs.knowledge.default_tuning_profile),
      group: 'recall'
    });
    out.push({
      label: 'Judge',
      model: dash(ev.judge_model || answering),
      tuning: tuningChips(ev.judge_tuning_profile),
      group: 'recall'
    });
    return out;
  });
  const ingestModels = $derived(modelLines.filter((m) => m.group === 'ingest'));
  const recallModels = $derived(modelLines.filter((m) => m.group === 'recall'));

  // Answer-prompt picker options (memory track). The locked "default" profile is exposed as value
  // '' so an unset run maps to it; the others by id. Authored in Preferences → Graph Engine.
  const answerPromptOptions = $derived.by<{ id: string; label: string }[]>(() => {
    const lib = prefs?.graph.eval.answer_prompts ?? {};
    const def = lib['default'];
    const out = [{ id: '', label: def ? def.label : 'Default' }];
    for (const [id, p] of Object.entries(lib)) {
      if (id === 'default') continue;
      out.push({ id, label: p.label });
    }
    return out;
  });
  // The selected profile's label — the run's answer-prompt provenance, shown in the settings strip.
  const answerPromptLabel = $derived(
    answerPromptOptions.find((o) => o.id === eval_.answerPromptId)?.label ??
      answerPromptOptions[0]?.label ??
      'Default'
  );

  // Non-model ingestion knobs. Extraction ontology (open vs typed) governs what the graph build
  // extracts, so it applies to BOTH tracks; knowledge chunking knobs are knowledge-only. Shown in
  // the read-only Ingestion settings column — the Ingest button always describes what it will do.
  const ingestKnobs = $derived.by<Param[]>(() => {
    if (!prefs) return [];
    const g = prefs.graph;
    const out: Param[] = [
      { label: 'Extraction ontology', value: g.entity_ontology === 'typed' ? 'typed' : 'open' }
    ];
    if (!isMemory) {
      const c = prefs.knowledge.chunking;
      out.push(
        { label: 'Chunk size', value: String(c.chunk_size) },
        { label: 'Chunk overlap', value: String(c.chunk_overlap) },
        { label: 'Structural ctx', value: onOff(c.embed_structural_context) }
      );
    }
    return out;
  });

  const recallKnobs = $derived.by<Param[]>(() => {
    if (!prefs) return [];
    const g = prefs.graph;
    const out: Param[] = [
      { label: 'Temporal lens', value: TEMPORAL_LENS_LABEL[g.temporal_default] ?? g.temporal_default },
      { label: 'Hops', value: String(g.k_hop) },
      { label: 'Recipe', value: g.search_recipe },
      { label: 'Scope', value: g.search_scope },
      { label: 'Sim floor', value: String(g.sim_min_score) }
    ];
    if (g.search_recipe === 'cross_encoder') {
      out.push({ label: 'Graph reranker', value: dash(g.reranker.model_id) });
      out.push({ label: 'Rerank floor', value: String(g.reranker.min_relevance) });
    }
    if (isMemory) {
      out.push({ label: 'Recall top-k', value: String(prefs.memory.search.top_k) });
      // Provenance: which answer-prompt profile this run will use (label-tags the run).
      out.push({ label: 'Answer prompt', value: answerPromptLabel });
    } else {
      const r = prefs.knowledge.retrieval;
      out.push({ label: 'Retrieval top-k', value: String(r.top_k) });
      out.push({ label: 'Flat min score', value: String(r.min_score) });
      out.push({ label: 'Hybrid', value: onOff(r.hybrid) });
      out.push({ label: 'Prefetch', value: String(r.prefetch_limit) });
      if (r.reranker.enabled) {
        out.push({ label: 'Flat reranker', value: dash(r.reranker.model_id) });
        out.push({ label: 'Rerank top-n', value: String(r.reranker.top_n) });
      }
    }
    out.push({ label: 'Observability', value: g.observability });
    return out;
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

  // Two explicit actions (one button each): Ingest builds the graph (needs only a corpus); Eval
  // Questions answers the selection (needs a non-empty selection). Both are blocked while a run is
  // in flight (canRun is false then) or before a corpus is picked.
  const ingestDisabled = $derived(!canRun || !eval_.selectedCorpus);
  const evalDisabled = $derived(!canRun || !eval_.selectedCorpus || eval_.selectedCount === 0);
  const ingestTitle = $derived(
    !eval_.selectedCorpus
      ? 'Pick a corpus first'
      : isMemory
        ? 'Remember the chosen episode window into the graph (no questions)'
        : 'Ingest the corpus (+ rebuild the graph if checked)'
  );
  const evalTitle = $derived(
    !eval_.selectedCorpus
      ? 'Pick a corpus first'
      : eval_.selectedCount === 0
        ? 'Select at least one question to evaluate'
        : 'Answer the selected questions against the existing graph'
  );

  // Which action is in flight (drives the spinner + Cancel placement). Set when each button fires;
  // null for a run we only learned about via hydration (mid-run navigation) — Cancel then defaults
  // to the Question-answering section.
  let runningIntent = $state<'ingest' | 'questions' | null>(null);
  $effect(() => {
    if (!isBusy) runningIntent = null;
  });

  // Wipe guard: an INGEST run that will WIPE an existing graph — memory "Clear graph first", or the
  // knowledge "Rebuild graph" — opens a confirm dialog first (the wipe is destructive + costs money
  // to rebuild). Eval never ingests, so it never wipes → it runs straight away.
  let confirmOpen = $state(false);
  function requestIngest() {
    runningIntent = 'ingest';
    const wipes = isMemory ? eval_.clearBefore : eval_.rebuildChecked;
    if (wipes && eval_.selectedCorpusHasGraph) confirmOpen = true;
    else void eval_.start('ingest');
  }
  function requestEval() {
    runningIntent = 'questions';
    void eval_.start('questions');
  }

  // Clear guard: the memory-track clear PERMANENTLY deletes saved results from disk
  // (eval_.clear → clearEvalResults), so it's gated behind a confirm. The knowledge-track "Clear"
  // only resets the in-view run state (non-destructive) and clears straight away.
  let clearConfirmOpen = $state(false);
  function requestClear() {
    if (isMemory) clearConfirmOpen = true;
    else void eval_.clear();
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

  /** Short verdict word for the judge line badge. */
  function markLabel(mark: string): string {
    if (mark === '✓') return 'Pass';
    if (mark === '◐') return 'Partial';
    if (mark === '✗') return 'Fail';
    if (mark === '🛇') return 'Abstain';
    return 'Not judged';
  }

  /** Color the evidence-recall X/Y chip: all gold episodes recalled → green, some → amber, none →
   *  red. ``total === 0`` shouldn't reach a badge (caller renders a dash), but is neutral if it does. */
  function evidenceVariant(matched: number, total: number): 'success' | 'warning' | 'destructive' | 'secondary' {
    if (total <= 0) return 'secondary';
    if (matched >= total) return 'success';
    if (matched > 0) return 'warning';
    return 'destructive';
  }

  /** Whole-number percentage for the report tables (n/total ⇒ "0"–"100"); "—" when total is 0. */
  function pct(n: number, total: number): string {
    if (!total || total <= 0) return '—';
    return `${Math.round((n / total) * 100)}%`;
  }

  /** Score can be fractional (partial = ½ pt); show one decimal only when needed (e.g. 12.5, 13). */
  function fmtScore(n: number): string {
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
  }

  // Eval-time helpers for the "Time" column: clock-only display, full date in the tooltip, and an
  // epoch-ms key for sorting (so we display the time but order by the actual date).
  function fmtTime(iso: string | undefined): string {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  function fmtDateTime(iso: string | undefined): string {
    if (!iso) return 'Not run yet';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }
  function timeMs(iso: string | undefined): number {
    const t = iso ? Date.parse(iso) : NaN;
    return Number.isNaN(t) ? 0 : t;
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
  // Memory shows a sortable recall-sufficiency flag column (before the recall answer).
  const showRecallCol = $derived(isMemory);
  // Memory also shows an evidence-recall column (X/Y gold evidence episodes covered) — populated
  // only for LoCoMo corpora; other corpora render a dash.
  const showEvidenceCol = $derived(isMemory);
  // Whether the report's evidence-recall metric column should show: memory track AND the summary
  // actually carries gold-evidence totals (LoCoMo corpora only). Non-LoCoMo memory reports skip it
  // rather than render a column of dashes.
  const hasEvidenceReport = $derived.by(() => {
    const s = eval_.summary;
    if (!isMemory || !s) return false;
    const buckets = [
      ...Object.values(s.by_category ?? {}),
      ...Object.values(s.by_difficulty ?? {})
    ];
    return buckets.some((b) => (b.evidence_total ?? 0) > 0);
  });
  // Full-width row colspan: #, Question, Type, Difficulty, Ideal, [recall flag], [evidence],
  // [answer type], <N legs>, [Δ], Time. (Trace/recall links moved out of the main row into the
  // expanded fold; the answer-type column is memory-only — the verdict split out of the answer cell.)
  const resultsColspan = $derived(
    5 +
      legColumns.length +
      (showDelta ? 1 : 0) +
      (showRecallCol ? 1 : 0) +
      (showEvidenceCol ? 1 : 0) +
      (isMemory ? 1 : 0) +
      1
  );

  // Answer-details sort (within each category group), by any sortable column. Per column: click
  // cycles none→asc→desc; ``none`` keeps the natural question-index order. Sorting is intra-group
  // (rows are grouped by type), so category isn't a sort key — type is constant within a group.
  type AnsSortKey = 'none' | 'recall' | 'time' | 'difficulty' | 'evidence' | 'mark';
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
  // Recall rank for a row's recall leg: miss (0), sufficient (1), unknown/not-judged (2).
  function rowRecallRank(r: EvalRow): number {
    const leg = r.legs?.recall;
    if (!leg?.mark) return 2;
    return leg.recall_sufficient === false ? 0 : 1;
  }
  // Difficulty rank for sorting (medium < hard < very_hard < unspecified), reusing the questions
  // ramp; unknown/unspecified sort last in ascending.
  function rowDiffRank(r: EvalRow): number {
    return _DIFF_SORT[r.difficulty || ''] ?? 3;
  }
  // Evidence-recall sort key: the matched/total fraction (lower = worse, sorts first ascending);
  // rows with no gold evidence (total 0 / non-LoCoMo) get 2 so they sort LAST in ascending — same
  // "n/a last" convention as the recall-sufficiency column.
  function rowEvidenceRank(r: EvalRow): number {
    const ev = r.evidence_recall;
    if (!ev || ev.total <= 0) return 2;
    return ev.matched / ev.total;
  }
  // Answer-type (judge mark) rank for the recall leg, reusing the saved-state order
  // (✓ < ◐ < ✗ < 🛇 < not-judged). Memory-only column, so it reads the single recall leg.
  function rowMarkRank(r: EvalRow): number {
    return _STATE_SORT[r.legs?.recall?.mark ?? ''] ?? 4;
  }
  // Apply the active sort to a group's rows (stable on index); identity when sort is off.
  function sortGroupRows(rows: EvalRow[]): EvalRow[] {
    if (ansSortKey === 'none') return rows;
    const dir = ansSortDir === 'asc' ? 1 : -1;
    const key =
      ansSortKey === 'recall'
        ? rowRecallRank
        : ansSortKey === 'time'
          ? (r: EvalRow) => timeMs(r.answered_at)
          : ansSortKey === 'difficulty'
            ? rowDiffRank
            : ansSortKey === 'evidence'
              ? rowEvidenceRank
              : rowMarkRank; // 'mark'
    return [...rows].sort((a, b) => dir * (key(a) - key(b)) || a.index - b.index);
  }

  // --- Answer Details filters (search + type + difficulty + recall flag + answer type) --------
  // View-only filters over the answer rows, mirroring the Questions-tab filter bar. The search
  // matches EVERYTHING the row carries — including the folded detail (judge reason/evidence and
  // the recalled facts/entities/episodes) — so a recalled fact's text finds its question.
  type AnsFlag = 'all' | 'sufficient' | 'miss' | 'unknown';
  type AnsMark = 'all' | 'pass' | 'partial' | 'fail' | 'abstain' | 'not_judged';
  let ansSearch = $state('');
  // Whether the search also looks inside the recalled facts/entities/episodes (the folded memory
  // detail). Off by default — recall dumps are large and noisy, so the search stays on the answer
  // surface (question/ideal/answer/judge) unless the user opts in.
  let ansSearchRecalled = $state(false);
  let ansCategory = $state<string>('all');
  let ansDifficulty = $state<QDifficulty>('all');
  let ansFlag = $state<AnsFlag>('all');
  let ansMark = $state<AnsMark>('all');
  // Term used to highlight inside the recalled tables — empty (no highlight) unless recalled search
  // is enabled, so recalled rows only light up when they're actually part of the search scope.
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
  // Judge-mark glyph → answer-type filter key ('' / unknown glyph ⇒ not judged).
  const MARK_FILTER_KEY: Record<string, AnsMark> = {
    '✓': 'pass',
    '◐': 'partial',
    '✗': 'fail',
    '🛇': 'abstain'
  };
  // Answer-type match: ANY leg with the selected verdict counts (memory has one recall leg;
  // knowledge legs are an at-a-glance OR — per-leg filtering isn't worth the extra controls).
  function rowMatchesMark(r: EvalRow): boolean {
    if (ansMark === 'all') return true;
    return Object.values(r.legs).some(
      (leg) => (MARK_FILTER_KEY[leg.mark] ?? 'not_judged') === ansMark
    );
  }
  // Recall-sufficiency flag match (memory only) — reuses rowRecallRank's miss/ok/unknown buckets.
  function rowMatchesFlag(r: EvalRow): boolean {
    if (ansFlag === 'all') return true;
    const rank = rowRecallRank(r);
    return ansFlag === 'miss' ? rank === 0 : ansFlag === 'sufficient' ? rank === 1 : rank === 2;
  }
  // Searchable text on a row: question/ideal/ids + per-leg answer, verdict word, judge reason +
  // quoted evidence. The folded memory detail (recalled facts/entities/episodes AND the evidence-
  // recall table) is included ONLY when the user enabled recalled search (``ansSearchRecalled``) —
  // that detail is large/noisy, so it's opt-in. When opted in, EVERY folded table is searched so a
  // term in any of them finds its question (previously the evidence-recall table was skipped).
  function rowHaystack(r: EvalRow): string {
    const parts: string[] = [r.id, r.category, r.subcategory, r.difficulty, r.question, r.gold];
    for (const leg of Object.values(r.legs)) {
      parts.push(leg.answer, markLabel(leg.mark), leg.reason ?? '', leg.evidence ?? '');
      if (ansSearchRecalled) {
        // Recalled facts / entities / episodes (the episodes table renders ``memory``/``valid_at``).
        for (const f of leg.recalled ?? []) {
          parts.push(
            f.memory,
            f.fact ?? '',
            f.name ?? '',
            f.summary ?? '',
            f.entity_type ?? '',
            f.valid_at ?? '',
            f.invalid_at ?? ''
          );
        }
      }
    }
    // Evidence-recall table (per-row, LoCoMo) — the gold evidence episodes. Folded into the search
    // alongside the recalled tables so a term in an evidence episode also surfaces the question.
    if (ansSearchRecalled) {
      for (const it of r.evidence_recall?.items ?? []) {
        parts.push(
          it.episode_id,
          it.short_id ?? '',
          it.dia_id ?? '',
          it.speaker ?? '',
          it.text ?? '',
          it.when ?? '',
          it.matched_via ?? ''
        );
      }
    }
    return parts.join(' ').toLowerCase();
  }
  const filteredAnswerRows = $derived.by(() => {
    const term = ansSearch.trim().toLowerCase();
    return eval_.rows.filter((r) => {
      if (ansCategory !== 'all' && (r.category || '') !== ansCategory) return false;
      if (ansDifficulty !== 'all' && (r.difficulty || 'unspecified') !== ansDifficulty)
        return false;
      if (isMemory && !rowMatchesFlag(r)) return false;
      if (!rowMatchesMark(r)) return false;
      if (term && !rowHaystack(r).includes(term)) return false;
      return true;
    });
  });

  // --- Results grouped by type (category) ----------------------------------------------------
  // FILTERED rows grouped by category in first-seen order, ordered by question index within each
  // group; groups emptied by the Answer Details filters disappear. Each group is collapsible;
  // expand/collapse-all act on every group.
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
  // Full per-episode trace list for the open run + current index, so the dialog's prev/next arrows
  // (and ←/→) can step through every episode of the remember run. Each eval turn is its own
  // single-episode ingest, so a trace's own episode_index/total is always 1/1 — the real run
  // position is this index, fed to the dialog as navIndex/navTotal.
  let ingestTraces = $state<IngestTraceRecord[]>([]);
  let ingestTraceIndex = $state(0);
  let ingestTraceLoading = $state(false);
  let ingestTraceError = $state<string | null>(null);
  async function openIngestTrace(runId: string) {
    ingestTraceError = null;
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        // Keep the WHOLE list (not just traces[0]) so arrow-nav can walk every episode. The Corpus
        // tab shows the full (searchable) corpus regardless of which episode is shown.
        ingestTraces = traces;
        ingestTraceIndex = 0;
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

  /** Open the ingest-pipeline dialog for ONE corpus episode (from the Corpus tab's "pipeline"
   *  button). Loads that episode's remember run, then positions the dialog on the matching episode
   *  (by chunk_id, falling back to step_index) so it opens straight to that turn's pipeline —
   *  prev/next still walks the whole run, same as the run-level "Ingest pipeline" button. */
  async function openIngestTraceForEpisode(info: {
    id: string;
    runId: string;
    stepIndex: number | '';
  }) {
    ingestTraceError = null;
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(info.runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length === 0) {
        ingestTraceError = 'No ingest trace recorded for this episode (graph tracing may have been off).';
        return;
      }
      let idx = traces.findIndex((t) => t.chunk_id === info.id);
      if (idx < 0 && info.stepIndex !== '') idx = traces.findIndex((t) => t.step_index === info.stepIndex);
      ingestTraces = traces;
      ingestTraceIndex = idx >= 0 ? idx : 0;
      activeIngestTrace = traces[ingestTraceIndex];
    } catch (err) {
      ingestTraceError = err instanceof Error ? err.message : 'Failed to load ingest trace.';
    } finally {
      ingestTraceLoading = false;
    }
  }

  /** Open the Knowledge Graph view (Memories page, Graph tab) focused on ONE corpus episode:
   *  seed the active group + that episode's chunk_id into the graph's session state, then navigate.
   *  The graph panel restores both on mount, landing pre-filtered to this episode's entities/facts.
   *  No-op if the corpus's eval group isn't known yet (extraction not loaded / untraced corpus). */
  function openGraphForEpisode(info: { id: string }) {
    const group = eval_.corpusExtractionGroup;
    if (!group) return;
    seedGraphEpisodeFocus(group, info.id);
    void goto('/memories?tab=graph');
  }

  /** Step the open ingest-trace dialog to the prev/next episode of the run (arrow-nav). */
  function stepIngestTrace(delta: number) {
    const j = ingestTraceIndex + delta;
    if (j >= 0 && j < ingestTraces.length) {
      ingestTraceIndex = j;
      activeIngestTrace = ingestTraces[j];
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

  // Answer-mark groups for the report tables: colored icon + name (reuses the savedBadge icons).
  const MARK_GROUP_META = [
    { key: 'pass', name: 'Pass', Icon: CircleCheck, cls: 'text-emerald-600 dark:text-emerald-400' },
    { key: 'partial', name: 'Partial', Icon: CircleDashed, cls: 'text-amber-600 dark:text-amber-400' },
    { key: 'fail', name: 'Fail', Icon: CircleX, cls: 'text-rose-600 dark:text-rose-400' },
    { key: 'abstain', name: 'Abstain', Icon: CircleSlash, cls: 'text-muted-foreground' }
  ] as const;

  // Sum all per-bucket rows of a breakdown into one totals row (the table's "Total" line).
  function breakdownTotals(
    bc: Record<string, EvalCategoryStat>,
    cols: string[]
  ): EvalCategoryStat {
    const t: EvalCategoryStat = {
      total: 0,
      groups: Object.fromEntries(
        cols.map((m) => [m, { pass: 0, partial: 0, fail: 0, abstain: 0 }])
      ),
      correct: Object.fromEntries(cols.map((m) => [m, 0])),
      score: Object.fromEntries(cols.map((m) => [m, 0])),
      recall_ok: Object.fromEntries(cols.map((m) => [m, 0])),
      evidence_matched: 0,
      evidence_total: 0
    };
    for (const st of Object.values(bc)) {
      t.total += st.total;
      // Evidence recall is a single (non-leg) concept — sum the bucket scalars directly.
      t.evidence_matched = (t.evidence_matched ?? 0) + (st.evidence_matched ?? 0);
      t.evidence_total = (t.evidence_total ?? 0) + (st.evidence_total ?? 0);
      for (const m of cols) {
        const g = st.groups?.[m];
        if (g) {
          t.groups[m].pass += g.pass;
          t.groups[m].partial += g.partial;
          t.groups[m].fail += g.fail;
          t.groups[m].abstain += g.abstain;
        }
        t.correct[m] += st.correct?.[m] ?? 0;
        t.score[m] += st.score?.[m] ?? 0;
        t.recall_ok[m] += st.recall_ok?.[m] ?? 0;
      }
    }
    return t;
  }

</script>

<svelte:document onvisibilitychange={onVisibilityChange} />

<section class="grid gap-4">
  <!-- Error banners — kept ABOVE the sub-tabs so transport/scan failures stay visible whatever
       section is open. -->
  {#if eval_.status === 'failed' && eval_.failureMessage}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
      Eval run failed: {eval_.failureMessage}
    </div>
  {/if}
  {#if eval_.corpusesError}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
      {eval_.corpusesError}
    </div>
  {/if}

  <!-- Sticky section sub-tabs — pin directly under the page header; each section's
       summaries / buttons / filters render right under the bar (inside the matching pane). -->
  <div
    bind:this={subtabsEl}
    class="sticky z-10 bg-background/95 py-1 backdrop-blur supports-[backdrop-filter]:bg-background/85 {ADMIN_SHELL_STICKY_BLEED}"
    style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px));"
  >
    <AdminSubtabStrip
      ariaLabel="Eval section"
      tabs={subtabs}
      active={activeSubtab}
      onSelect={(id) => (activeSubtab = id)}
    />
  </div>

  <!-- ===== Execute pane ===== -->
  <!-- One card with everything to configure + launch a run, split into three parts: (1) Corpus
       scan + selection, (2) Ingestion (build options + read-only ingestion settings), (3) Question
       answering (answer/recall options + read-only answer/recall settings). The run action bar
       (selected-question count + Cancel + Run) sits at the top; Settings are editable via the
       Graph engine link. -->
  {#if activeSubtab === 'execute'}
    <div class="grid gap-4 rounded-md border bg-muted/10 px-3 py-3">
      <!-- Part 1 — Corpus: folder scan + corpus selection. -->
      <div class="grid gap-2">
        <p class="font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Corpus</p>
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
        </div>
      </div>

      <!-- Part 2 — Ingestion: two columns — left = build options + the Ingest button; right = the
           read-only ingestion settings (models + chunking) with the gear to edit them. -->
      <div class="grid gap-2 border-t pt-3">
        <p class="font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Ingestion</p>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="flex flex-col gap-3">
            <div class="flex flex-wrap items-center gap-3">
              {@render ingestionOptions()}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <Button disabled={ingestDisabled} onclick={requestIngest} title={ingestTitle}>
                {#if isBusy && runningIntent === 'ingest'}
                  <LoaderCircle size={14} class="animate-spin" />
                {:else}
                  <Download size={14} />
                {/if}
                Ingest
              </Button>
              {#if isBusy && runningIntent === 'ingest'}{@render cancelButton()}{/if}
            </div>
          </div>
          {@render settingsColumn(ingestModels, ingestKnobs)}
        </div>
      </div>

      <!-- Part 3 — Question answering: two columns — left = answer/recall options + the selected
           count and the Eval Questions button; right = the read-only answer/recall settings. -->
      <div class="grid gap-2 border-t pt-3">
        <p class="font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Question answering</p>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="flex flex-col gap-3">
            <div class="flex flex-wrap items-center gap-3">
              {@render answeringOptions()}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-sans text-xs text-muted-foreground" title="Questions selected to evaluate">
                <span class="font-mono tabular-nums text-foreground">{eval_.selectedCount}</span>
                {eval_.selectedCount === 1 ? 'question' : 'questions'} selected
              </span>
              <Button disabled={evalDisabled} onclick={requestEval} title={evalTitle}>
                {#if isBusy && runningIntent !== 'ingest'}
                  <LoaderCircle size={14} class="animate-spin" />
                {:else}
                  <Play size={14} />
                {/if}
                Eval Questions
              </Button>
              {#if isBusy && runningIntent !== 'ingest'}{@render cancelButton()}{/if}
            </div>
          </div>
          {@render settingsColumn(recallModels, recallKnobs)}
        </div>
      </div>
    </div>
  {/if}

  <!-- ===== Corpus pane (memory track) ===== -->
  <!-- Corpus review (memory track) — a human-readable look at the turn corpus the questions
       probe: stats header (episode count / date span / question count + per-category breakdown)
       then the full episode transcript. Collapsed by default; sits above the questions. -->
  {#if activeSubtab === 'corpus' && isMemory && eval_.selectedCorpus}
      {#if eval_.corpusError}
        <p class="text-xs text-destructive">{eval_.corpusError}</p>
      {:else if eval_.corpusEpisodes.length === 0 && !eval_.corpusLoading}
        <p class="text-xs text-muted-foreground">No episodes loaded.</p>
      {:else}
        <!-- Corpus stats line — scrolls away normally (the search + filters live on the sticky
             toolbar rendered by EvalCorpusReview below). -->
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
          <span class="text-muted-foreground">
            Episodes: <span class="font-mono text-foreground">{eval_.corpusMeta?.episode_count ?? 0}</span>
          </span>
          <span class="text-muted-foreground">
            Span: <span class="font-mono text-foreground">{corpusSpan}</span>
          </span>
          <span class="text-muted-foreground">
            Questions: <span class="font-mono text-foreground">{eval_.questions.length}</span>
          </span>
          <span class="text-muted-foreground">
            Ingested: <span class="font-mono text-foreground">{ingestedLabel.replace(/^ingested /, '')}</span>
          </span>
          {#if eval_.corpusLoading}
            <LoaderCircle size={14} class="animate-spin text-muted-foreground" aria-hidden="true" />
          {/if}
        </div>
        <!-- Episode transcript — grows with the page (no inner scroll). EvalCorpusReview renders the
             sticky search + filters toolbar (stickyTop), the per-episode extracted/not badge, and the
             graph + pipeline buttons. -->
        <EvalCorpusReview
          episodes={eval_.corpusEpisodes}
          bind:search={corpusSearch}
          showSearch={false}
          scroll={false}
          extraction={eval_.corpusExtraction}
          onOpenPipeline={openIngestTraceForEpisode}
          onOpenGraph={openGraphForEpisode}
          stickyTop="calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px))"
        />
      {/if}
  {/if}

  <!-- ===== Questions pane ===== -->
  <!-- Questions section — pick the questions to run (required; no implicit "run all"). -->
  {#if activeSubtab === 'questions'}
    {#if !eval_.selectedCorpus}
      <p class="rounded-md border bg-muted/20 px-3 py-6 text-center font-sans text-sm text-muted-foreground">
        Pick a corpus above to load its questions.
      </p>
    {:else}
    <!-- Filters / buttons / stats — sticky directly under the sub-tab bar so they stay reachable
         while scrolling the (un-scrolled, full-page) question list. -->
    <div
      bind:this={qControlsEl}
      class="sticky z-10 flex flex-wrap items-center gap-2 bg-background py-2"
      style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px));"
    >
        <span class="mr-auto font-sans text-xs text-muted-foreground">{questionsSummary}</span>
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
        <!-- Selection is driven by the table's header checkbox (all shown) + per-row checkboxes.
             Clear selection (filters-bar button) drops *all* selected questions regardless of
             the active filters — added so a large selection can be reset without un-filtering. -->
        {#if eval_.selectedCount > 0}
          <button
            type="button"
            class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
            disabled={isBusy}
            onclick={() => eval_.clearSelection()}
            title="Clear all selected questions"
          >
            Clear selection
          </button>
        {/if}
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:opacity-50"
          disabled={isBusy}
          onclick={() => void eval_.loadQuestions()}
        >
          Reload
        </button>
    </div>
      {#if eval_.questionsError}
        <p class="text-xs text-destructive">{eval_.questionsError}</p>
      {:else if eval_.questions.length === 0 && !eval_.questionsLoading}
        <p class="text-xs text-muted-foreground">No questions loaded.</p>
      {:else}
        <!-- Flat sortable question table — one row per question: select · type · state · # ·
             question · difficulty. Sticky head (pins below the sticky filters bar); sortable
             columns. Select-all (head) + the Select/Clear-shown buttons act on the visible set.
             No overflow wrapper — that would trap the sticky head against a scroll box. -->
        <div class="mt-2 rounded-md border">
          <table class="w-full border-collapse font-sans text-sm">
            <thead
              class="bg-muted text-xs uppercase tracking-wide text-muted-foreground [&_th]:sticky [&_th]:top-[calc(4rem+var(--admin-page-header-h,0px)+var(--admin-page-sticky-toolbar-h,0px)+var(--admin-eval-subtabs-h,0px)+var(--admin-eval-qcontrols-h,0px))] [&_th]:z-10 [&_th]:border-b [&_th]:bg-muted"
            >
              <tr>
                <th class="px-2 py-1.5 text-left">
                  <input
                    type="checkbox"
                    class="size-3.5 align-middle"
                    checked={allSelected}
                    disabled={filteredQuestions.length === 0 || isBusy}
                    onchange={(e) => eval_.setCategorySelected(filteredIds, e.currentTarget.checked)}
                    title="Select / deselect all shown"
                    aria-label="Select all shown"
                  />
                </th>
                {@render sortHeader('category', 'Type')}
                {#if isMemory}{@render sortHeader('state', 'State')}{/if}
                {#if isMemory}{@render sortHeader('recall', 'Recall sufficiency', false, Flag, 'Judge recall-sufficiency — sort')}{/if}
                {@render sortHeader('number', '#', true)}
                {@render sortHeader('question', 'Question')}
                {@render sortHeader('difficulty', 'Difficulty')}
                {#if isMemory}{@render sortHeader('time', 'Time', true)}{/if}
              </tr>
            </thead>
            <tbody>
              {#if sortedQuestions.length === 0}
                <tr>
                  <td colspan={qColspan} class="px-2 py-3 text-center font-sans text-xs text-muted-foreground">
                    No questions match the filters.
                  </td>
                </tr>
              {/if}
              {#each sortedQuestions as q (q.id)}
                {@const dm = difficultyMeta(q.difficulty ?? '')}
                {@const sb = savedBadge(q.id)}
                {@const SavedIcon = sb?.Icon}
                <tr class="border-t align-top hover:bg-muted/40 {eval_.isSelected(q.id) ? 'bg-primary/5' : ''}">
                  <td class="px-2 py-1.5">
                    <input
                      type="checkbox"
                      class="size-3.5 align-middle"
                      checked={eval_.isSelected(q.id)}
                      disabled={isBusy}
                      onchange={() => eval_.toggleQuestion(q.id)}
                      aria-label="Select question"
                    />
                  </td>
                  <td class="px-2 py-1.5 text-xs text-muted-foreground">{q.category || '—'}</td>
                  {#if isMemory}
                    <td class="px-2 py-1.5">
                      {#if sb && SavedIcon}
                        <span class="inline-flex items-center gap-1 {sb.cls}" title={sb.title} aria-label={sb.title}>
                          <SavedIcon size={14} class="shrink-0" aria-hidden="true" />
                          <span class="text-xs">{savedStateName(q.id)}</span>
                        </span>
                      {:else}
                        <span class="text-xs text-muted-foreground">—</span>
                      {/if}
                    </td>
                    <!-- Judge recall-sufficiency flag (no text). -->
                    <td class="px-2 py-1.5 text-center">{@render recallFlag(eval_.savedRecallSufficient(q.id))}</td>
                  {/if}
                  <td class="px-2 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {questionNumber.get(q.id) ?? ''}
                  </td>
                  <td class="px-2 py-1.5">
                    {q.question}
                    {#if q.subcategory}<span class="text-xs text-muted-foreground"> · {q.subcategory}</span>{/if}
                  </td>
                  <td class="px-2 py-1.5">
                    {#if dm}
                      <span
                        class="inline-block rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide {dm.cls}"
                      >{dm.label}</span>
                    {:else}
                      <span class="text-xs text-muted-foreground">—</span>
                    {/if}
                  </td>
                  {#if isMemory}
                    <!-- Eval time — clock only; full date on hover; sorts on the underlying date. -->
                    <td
                      class="whitespace-nowrap px-2 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground"
                      title={fmtDateTime(eval_.savedAnsweredAt(q.id))}
                    >{fmtTime(eval_.savedAnsweredAt(q.id))}</td>
                  {/if}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/if}
  {/if}

  <!-- Cost — its own strip (NOT nested in Results) so it shows during ingestion too: the memory
       remember/graph-build phase is the priciest part and runs before any question row exists, so
       a Results-gated cost box reported nothing while ingesting. Ingest cost streams in on the
       'remember_done' setup event; questions accumulate live; total folds both (LLM + reranker;
       embeddings unpriced). Knowledge ingest cost is deferred (multi-run), shown as “—”. -->
  {#if activeSubtab === 'execute' && (totalCost > 0 || isBusy)}
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

  <!-- Activity section — only once processing starts (or has data to replay). Persists across
       navigation via the server-side run registry (GET /knowledge/eval/state). Shown below Cost. -->
  {#if activeSubtab === 'execute' && (isBusy || eval_.setupEvents.length > 0 || eval_.rows.length > 0)}
    <KnowledgeCollapsibleSectionCard
      title="Activity"
      bodyId="knowledge-eval-activity"
      defaultExpanded={false}
      collapsedSummary={currentActivityLine}
    >
      <KnowledgeEvalTerminal lines={activityLines} />
    </KnowledgeCollapsibleSectionCard>
  {/if}

  <!-- ===== Answer Details pane ===== -->
  <!-- Per-question answers, grouped by type: Question, Ideal, Model answer(s) at a glance;
       fold for recalled facts / judge reason / full answers / run links. -->
  {#if activeSubtab === 'answers'}
    {#if !(eval_.rows.length > 0 || eval_.summary)}
      <p class="rounded-md border bg-muted/20 px-3 py-6 text-center font-sans text-sm text-muted-foreground">
        No answers yet — run an eval to see per-question results here.
      </p>
    {:else}
    <!-- Actions / filters / stats — sticky directly under the sub-tab bar so the search + filters
         stay reachable while scrolling the (full-page) results table. The table's sticky thead pins
         beneath this bar via the --admin-eval-acontrols-h offset it publishes. -->
    <div
      bind:this={aControlsEl}
      class="sticky z-10 flex flex-wrap items-center gap-2 bg-background py-2"
      style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px));"
    >
        <span class="mr-auto font-sans text-xs text-muted-foreground">
          {resultsSummary}{#if ansFiltered}
            · {filteredAnswerRows.length}/{eval_.rows.length} shown{/if}
        </span>
        <!-- Filters: deep search (folded detail included) + type + difficulty + flag + answer type. -->
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
        <!-- Opt-in: also search every folded table — recalled facts/entities/episodes AND the
             evidence-recall episodes. Off by default — that detail is large/noisy. When on,
             matching rows in those tables also highlight. -->
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
        {#if isMemory}
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
        <!-- Expand / collapse all result type-groups (icons only). -->
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
    </div>
      {#if eval_.rows.length > 0 || eval_.status === 'running'}
        {@render resultsTable()}
      {/if}
    {/if}
  {/if}

  <!-- Clear-results action for the Report header — wipes ALL report data + answer details for this
       corpus (memory: a destructive on-disk delete, gated by the confirm dialog; knowledge: an
       in-view reset). Lives on the Report header line since that's the data it clears. -->
  {#snippet reportHeaderActions()}
    {#if eval_.rows.length > 0 || eval_.summary || eval_.failureMessage || (isMemory && eval_.savedCount > 0)}
      <Button
        variant="outline"
        class="h-7"
        disabled={isBusy}
        onclick={requestClear}
        title={isMemory
          ? 'Delete this corpus’s saved results from disk — wipes the report + answer details (ingested memory is kept)'
          : "Clear this run's report + answer details"}
      >
        <Trash2 size={14} /> {isMemory ? 'Clear results' : 'Clear'}
      </Button>
    {/if}
  {/snippet}

  <!-- ===== Report pane ===== -->
  <!-- Aggregate breakdown — per-category, then per-difficulty (answer-type distribution + Recall
       Accuracy / Score / Correct / Evidence recall + a Total row). Its own sub-tab (last); rendered
       directly under the tab (no collapsible card). A header line carries the run summary + the
       Clear-results action (which wipes the report + answer details). -->
  {#if activeSubtab === 'report'}
    {#if !eval_.summary}
      <p class="rounded-md border bg-muted/20 px-3 py-6 text-center font-sans text-sm text-muted-foreground">
        No report yet — run an eval to see the aggregate breakdown here.
      </p>
    {:else}
      <div class="flex flex-wrap items-center gap-2">
        <span class="mr-auto font-sans text-xs text-muted-foreground">{reportSummary}</span>
        {@render reportHeaderActions()}
      </div>
      {#if eval_.summary.by_category && Object.keys(eval_.summary.by_category).length > 0}
        <p class="mb-1 mt-2 font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Results by category
        </p>
        {@render breakdownTable(eval_.summary.by_category, eval_.summary.modes, 'Category')}
      {/if}
      {#if eval_.summary.by_difficulty && Object.keys(eval_.summary.by_difficulty).length > 0}
        <p class="mb-1 mt-3 font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Results by difficulty
        </p>
        {@render breakdownTable(
          orderedDifficulty(eval_.summary.by_difficulty),
          eval_.summary.modes,
          'Difficulty'
        )}
      {/if}
    {/if}
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
<!-- Corpus tab for the ingest trace dialog: built-in search box (that dialog has no top search). -->
{#snippet corpusTab()}
  <EvalCorpusReview episodes={eval_.corpusEpisodes} compact />
{/snippet}
<!-- Corpus tab for the retrieval trace dialog: filtering is driven by the dialog's top search
     (passed in), so there's no second search box here — just the match count + transcript. -->
{#snippet corpusTabWired(dialogSearch: string)}
  <EvalCorpusReview
    episodes={eval_.corpusEpisodes}
    search={dialogSearch}
    showSearch={false}
    showCount
    compact
  />
{/snippet}
<GraphRunsRetrievalTraceDialog
  trace={activeTrace}
  idealAnswer={activeTraceIdeal}
  llmAnswer={activeTraceAnswer}
  onClose={() => (activeTrace = null)}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTabWired : undefined}
/>
<!-- Ingest (graph-build) pipeline trace — opened from the Cost strip's "Ingest pipeline" button;
     same Corpus tab so the source transcript is reachable while inspecting the build. -->
<GraphRunsIngestTraceDialog
  trace={activeIngestTrace}
  onClose={() => {
    activeIngestTrace = null;
    ingestTraces = [];
    ingestTraceIndex = 0;
  }}
  hasPrev={ingestTraceIndex > 0}
  hasNext={ingestTraceIndex < ingestTraces.length - 1}
  onPrev={() => stepIngestTrace(-1)}
  onNext={() => stepIngestTrace(1)}
  navIndex={ingestTraces.length ? ingestTraceIndex + 1 : 0}
  navTotal={ingestTraces.length}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTab : undefined}
/>

<!-- Rebuild-graph wipe confirm — gates the Ingest button when a wipe (Clear graph / Rebuild graph)
     is armed on a graphed corpus. Only an ingest run wipes, so it always resumes as 'ingest'. -->
<KnowledgeEvalRebuildConfirmDialog
  bind:open={confirmOpen}
  track={eval_.track}
  corpusName={eval_.selectedCorpus?.name ?? ''}
  onConfirm={() => {
    confirmOpen = false;
    void eval_.start('ingest');
  }}
/>

<!-- Clear-results confirm — gates the memory track's destructive on-disk delete of saved results. -->
<KnowledgeEvalClearResultsConfirmDialog
  bind:open={clearConfirmOpen}
  corpusName={eval_.selectedCorpus?.name ?? ''}
  savedCount={eval_.savedCount}
  onConfirm={() => {
    clearConfirmOpen = false;
    void eval_.clear();
  }}
/>

<!-- Read-only settings block (models one-per-line + a dense knob chip row), rendered ALONG its
     matching Execute part — ingestion settings under Ingestion, answer/recall under Question
     answering. Editable via the Graph engine link in the Execute action bar. -->
{#snippet settingsBlock(models: ModelLine[], knobs: Param[])}
  <div class="grid gap-y-0.5 font-sans text-xs">
    {#each models as m (m.label)}
      <div class="flex flex-wrap items-baseline gap-x-2">
        <span class="w-20 shrink-0 text-muted-foreground">{m.label}</span>
        <span class="font-mono text-foreground">{m.model}</span>
        {#if m.tuning}<span class="text-muted-foreground">· {m.tuning}</span>{/if}
      </div>
    {/each}
  </div>
  {#if knobs.length > 0}
    <div class="flex flex-wrap gap-x-3 gap-y-0.5 font-sans text-xs">
      {#each knobs as p (p.label)}
        <span class="text-muted-foreground">{p.label}: <span class="font-mono text-foreground">{p.value}</span></span>
      {/each}
    </div>
  {/if}
{/snippet}

<!-- Right-hand settings column for an Execute part: a "Settings" label + a gear-only link to edit
     them in Graph engine, over the read-only settings block. Renders a hint when prefs aren't loaded. -->
{#snippet settingsColumn(models: ModelLine[], knobs: Param[])}
  <div class="min-w-0">
    <div class="mb-1 flex items-center justify-between gap-2">
      <span class="font-sans text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">Settings</span>
      <a
        href={preferenceTabHref('graph-engine', base)}
        title="Edit these settings in Graph engine"
        aria-label="Edit settings"
        class="inline-flex items-center rounded border p-1 text-primary hover:bg-primary/5"
      >
        <Settings2 size={14} aria-hidden="true" />
      </a>
    </div>
    {#if prefs}
      {@render settingsBlock(models, knobs)}
    {:else}
      <p class="font-sans text-xs text-muted-foreground">Settings unavailable.</p>
    {/if}
  </div>
{/snippet}

<!-- Cancel control for an in-flight run — shown in whichever Execute section's button row owns the
     running action (Ingest vs Eval). Cancel is global (one run at a time), so either placement stops it. -->
{#snippet cancelButton()}
  <Button
    variant="destructive"
    disabled={eval_.cancelling}
    onclick={() => void eval_.cancel()}
    title="Stop the running job"
  >
    {#if eval_.cancelling}
      <LoaderCircle size={14} class="animate-spin" />
    {:else}
      <Square size={14} />
    {/if}
    {eval_.cancelling ? 'Cancelling…' : 'Cancel'}
  </Button>
{/snippet}

<!-- Ingestion options — the knobs the Ingest button acts on (memory: episode window + Clear Graph;
     knowledge: Rebuild graph). The old "Ingest Episodes / Ingest corpus first" checkbox is gone —
     the Ingest button IS the ingest action. Caller wraps in a flex row; inputs disable while busy. -->
{#snippet ingestionOptions()}
  {#if !isMemory}
    <label
      class="flex select-none items-center gap-2 font-sans text-sm {isBusy ? 'opacity-50' : 'cursor-pointer'}"
      title="Wipe this corpus's prior graph, then rebuild it from the ingested chunks. Leave off to reuse the existing graph."
    >
      <input type="checkbox" class="size-4" bind:checked={eval_.buildGraph} disabled={isBusy} />
      <span>Rebuild graph</span>
    </label>
  {:else}
    <!-- Episode batch window — 1-based, INCLUSIVE episode numbers (episode 1 = the first turn):
         Ingest episodes From..To this run. To = 0 means "to the end". Build a large corpus in
         monitored chunks; the window auto-advances after each batch. (Controller converts to the
         backend's 0-based offset/count.) -->
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy ? 'opacity-50' : ''}"
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
    <!-- Clear Graph — explicit, decoupled wipe. VISIBLE but DIMMED when there's no graph to clear
         (nothing to wipe yet) or while a run is in flight. Off by default so a batched ingest
         APPENDS; the controller auto-resets it after an ingest starts so the next batch can't
         silently wipe the episodes just built. -->
    <label
      class="flex select-none items-center gap-2 font-sans text-sm {isBusy || !eval_.selectedCorpusHasGraph ? 'opacity-50' : 'cursor-pointer'}"
      title={eval_.selectedCorpusHasGraph
        ? 'Clear the graph before ingesting (WARNING: deletes every previously ingested episode for this corpus)'
        : 'No graph to clear yet — ingest first'}
    >
      <input
        type="checkbox"
        class="size-4"
        bind:checked={eval_.clearBefore}
        disabled={isBusy || !eval_.selectedCorpusHasGraph}
      />
      <span>Clear Graph</span>
    </label>
  {/if}
{/snippet}

<!-- Answering options — the knobs the Eval Questions button acts on: which legs to compare
     (knowledge), the optional LLM judge, and the parallel-question cap (memory). Judge + parallel
     only matter once questions are selected, so they're VISIBLE but DIMMED until then. -->
{#snippet answeringOptions()}
  {#if !isMemory}
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
  {/if}
  <label
    class="flex select-none items-center gap-2 font-sans text-sm {isBusy || eval_.selectedCount === 0 ? 'opacity-50' : 'cursor-pointer'}"
    title={eval_.selectedCount === 0
      ? 'Select questions to enable the LLM judge'
      : 'Grade each answer against the ideal with the LLM judge (off = recall results only)'}
  >
    <input
      type="checkbox"
      class="size-4"
      bind:checked={eval_.judge}
      disabled={isBusy || eval_.selectedCount === 0}
    />
    <span>LLM Judge Answers</span>
  </label>
  <!-- Memory track — parallel-question cap. 1 = serial (the safe default); higher overlaps each
       question's answer/judge LLM calls. Note: per-question times then include queueing, so the
       Time column isn't comparable across different caps. -->
  {#if isMemory}
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy || eval_.selectedCount === 0 ? 'opacity-50' : ''}"
      title="Questions evaluated in parallel (1 = one at a time). Higher is faster but per-question times include waiting, and aggressive caps can hit LLM provider rate limits."
    >
      <span class="text-muted-foreground">Parallel</span>
      <input
        type="number"
        min="1"
        max={eval_.questionConcurrencyMax}
        class="h-8 w-16 rounded-md border bg-background px-2 text-sm"
        value={eval_.questionConcurrency}
        oninput={(e) => (eval_.questionConcurrency = e.currentTarget.valueAsNumber)}
        disabled={isBusy || eval_.selectedCount === 0}
      />
    </div>
  {/if}
  <!-- Memory track — which named answer-prompt profile the recall leg's answer step uses. Authored
       in Preferences → Graph Engine; sticky per corpus (last-used). '' ⇒ the locked default. -->
  {#if isMemory}
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy ? 'opacity-50' : ''}"
      title="Named answer-prompt profile driving the answer step (edit profiles in Preferences → Graph Engine). Remembered per corpus."
    >
      <span class="text-muted-foreground">Answer prompt</span>
      <select
        class="h-8 rounded-md border bg-background px-2 text-sm"
        value={eval_.answerPromptId}
        onchange={(e) => (eval_.answerPromptId = e.currentTarget.value)}
        disabled={isBusy}
      >
        {#each answerPromptOptions as opt (opt.id)}
          <option value={opt.id}>{opt.label}</option>
        {/each}
      </select>
    </div>
  {/if}
{/snippet}

<!-- Judge recall-sufficiency flag — a single colored flag (no text): green = the recalled context
     held what was needed, rose = a recall miss. Renders nothing when unknown (not judged). -->
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

<!-- Sortable header cell for the Questions table: click to sort (toggles asc/desc); shows the
     active direction, or a faded both-ways glyph to signal the column is sortable. -->
{#snippet sortHeader(
  key: QSortKey,
  label: string,
  alignRight = false,
  IconCmp: Component<{ size?: number; class?: string }> | null = null,
  titleText = ''
)}
  <th class="px-2 py-1.5 {IconCmp ? 'text-center' : alignRight ? 'text-right' : 'text-left'}">
    <button
      type="button"
      class="inline-flex items-center gap-1 uppercase tracking-wide hover:text-foreground {alignRight && !IconCmp ? 'flex-row-reverse' : ''}"
      onclick={() => toggleSort(key)}
      title={titleText || `Sort by ${label}`}
    >
      {#if IconCmp}<IconCmp size={12} />{:else}{label}{/if}
      {#if qSortKey === key}
        {#if qSortDir === 'asc'}<ChevronUp size={12} aria-hidden="true" />{:else}<ChevronDown size={12} aria-hidden="true" />{/if}
      {:else}
        <ChevronsUpDown size={12} class="opacity-30" aria-hidden="true" />
      {/if}
    </button>
  </th>
{/snippet}

<!-- Sortable header cell for the Answer Details table: click cycles none→asc→desc (cycleAnsSort);
     shows the active direction, or a faded both-ways glyph to signal the column is sortable. Mirrors
     the Questions table's sortHeader but drives the answer-row sort. ``align`` positions the cell;
     pass an ``IconCmp`` for an icon-only header (e.g. the recall flag). -->
{#snippet ansSortHeader(
  key: Exclude<AnsSortKey, 'none'>,
  label: string,
  align: 'left' | 'center' | 'right' = 'left',
  IconCmp: Component<{ size?: number; class?: string }> | null = null,
  titleText = ''
)}
  <th class="px-2 py-1.5 {align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'}">
    <button
      type="button"
      class="inline-flex items-center gap-1 uppercase tracking-wide hover:text-foreground {align === 'right' ? 'flex-row-reverse' : ''}"
      onclick={() => cycleAnsSort(key)}
      title="{titleText || `Sort by ${label}`}{ansSortKey === key ? ` (${ansSortDir})` : ''}"
    >
      {#if IconCmp}<IconCmp size={12} />{:else}{label}{/if}
      {#if ansSortKey === key}
        {#if ansSortDir === 'asc'}<ChevronUp size={12} aria-hidden="true" />{:else}<ChevronDown size={12} aria-hidden="true" />{/if}
      {:else}
        <ChevronsUpDown size={12} class="opacity-30" aria-hidden="true" />
      {/if}
    </button>
  </th>
{/snippet}

<!-- Highlight the active Answer Details search term inside a text span (no {@html} — segments are
     plain text wrapped in <mark>, so corpus content can't inject). Identity render when no search. -->
{#snippet hl(text: string)}{#each highlightSegments(text ?? '', ansSearch) as seg}{#if seg.hit}<mark class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark>{:else}{seg.text}{/if}{/each}{/snippet}

<!-- Highlight inside the recalled tables — gated on ``recalledTerm`` (empty unless recalled search
     is enabled), so recalled text only lights up when it's part of the search scope. -->
{#snippet hlR(text: string)}{#each highlightSegments(text ?? '', recalledTerm) as seg}{#if seg.hit}<mark class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark>{:else}{seg.text}{/if}{/each}{/snippet}

<!-- Unified results table: Question, Ideal, per-leg [mark + model answer]; fold for details. -->
{#snippet resultsTable()}
  <!-- No overflow wrapper: a scroll container would trap the sticky header. The thead pins to
       the page scroll, offset below the sticky page header + run-controls toolbar. -->
  <div class="rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead
        class="text-xs uppercase tracking-wide text-muted-foreground [&_th]:sticky [&_th]:top-[calc(4rem+var(--admin-page-header-h,0px)+var(--admin-page-sticky-toolbar-h,0px)+var(--admin-eval-subtabs-h,0px)+var(--admin-eval-acontrols-h,0px))] [&_th]:z-10 [&_th]:border-b [&_th]:bg-muted"
      >
        <tr>
          <th class="px-2 py-1.5 text-left">#</th>
          <th class="px-2 py-1.5 text-left">Question</th>
          <th class="px-2 py-1.5 text-left">Type</th>
          {@render ansSortHeader('difficulty', 'Difficulty')}
          <th class="px-2 py-1.5 text-left">Ideal</th>
          {#if showRecallCol}
            <!-- Sortable recall-sufficiency flag column (before the recall answer). -->
            {@render ansSortHeader('recall', '', 'center', Flag, 'Judge recall-sufficiency')}
          {/if}
          {#if showEvidenceCol}
            <!-- Evidence recall — gold evidence episodes covered by the recall (X/Y). LoCoMo only. -->
            {@render ansSortHeader('evidence', 'Ev', 'center', null, 'Evidence recall — gold evidence episodes the recall covered (LoCoMo corpora)')}
          {/if}
          {#each legColumns as mode (mode)}
            {#if isMemory}
              <!-- Answer type (judge verdict) — split out of the recall-answer cell into its own
                   sortable column so the verdict scans/sorts independently of the answer text. -->
              {@render ansSortHeader('mark', 'Answer type')}
            {/if}
            <th class="px-2 py-1.5 text-left">{legLabel(mode)} answer</th>
          {/each}
          {#if showDelta}<th class="px-2 py-1.5 text-center" title="best graph leg vs flat">&#916;</th>{/if}
          <!-- Eval time (sortable, last column) — clock only; full date on hover; sorts on date. -->
          {@render ansSortHeader('time', 'Time', 'right', null, 'Eval time')}
        </tr>
      </thead>
      <tbody>
        {#if resultGroups.length === 0 && eval_.rows.length > 0}
          <!-- Rows exist but the Answer Details filters matched none of them. -->
          <tr>
            <td colspan={resultsColspan} class="px-2 py-3 text-center font-sans text-xs text-muted-foreground">
              No answers match the filters.
            </td>
          </tr>
        {/if}
        {#each resultGroups as [groupCat, groupRows] (groupCat)}
          {@const groupCollapsed = collapsedResultGroups.has(groupCat)}
          <!-- Type (category) group header — collapsible, spans the full table width. -->
          <tr class="border-t bg-muted/40">
            <td colspan={resultsColspan} class="px-2 py-1">
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
            {@const sortedRows = sortGroupRows(groupRows)}
            {#each sortedRows as r, gi (r.id)}
          <tr class="border-t align-top">
            <!-- Per-category position (n of this category's rows), not out of the whole run. -->
            <td class="px-2 py-1.5 font-mono tabular-nums text-xs text-muted-foreground">{gi + 1}/{sortedRows.length}</td>
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
                <span class="line-clamp-2" title={r.question}>{@render hl(r.question)}</span>
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
              <span class="line-clamp-2" title={r.gold || ''}>{#if r.gold}{@render hl(r.gold)}{:else}—{/if}</span>
            </td>
            {#if showRecallCol}
              <!-- Recall-sufficiency flag — its own (sortable) column, before the recall answer. -->
              {@const rleg = r.legs?.recall}
              <td class="px-2 py-1.5 text-center">
                {@render recallFlag(rleg?.mark ? (rleg.recall_sufficient ?? true) : undefined)}
              </td>
            {/if}
            {#if showEvidenceCol}
              <!-- Evidence recall X/Y — gold evidence episodes the recall covered (LoCoMo only). -->
              <td class="px-2 py-1.5 text-center">
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
              {#if isMemory}
                <!-- Answer type — the judge verdict alone (split from the recall answer). -->
                <td class="whitespace-nowrap px-2 py-1.5">
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
              <td class="px-2 py-1.5">
                {#if r.legs[mode]}
                  {@const leg = r.legs[mode]}
                  {#if isMemory}
                    <!-- Memory: answer text only — the verdict lives in the Answer type column. -->
                    <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}{@render hl(leg.answer)}{:else}— (no answer){/if}</span>
                  {:else}
                    <div class="flex items-start gap-1.5">
                      <Badge variant={markVariant(leg.mark)} class="mt-0.5 font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
                      <span class="line-clamp-2 text-sm" title={leg.answer || ''}>{#if leg.answer}{@render hl(leg.answer)}{:else}— (no answer){/if}</span>
                    </div>
                  {/if}
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
            <!-- Eval time — clock only; full date on hover; sorts on the underlying date. -->
            <td
              class="whitespace-nowrap px-2 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground"
              title={fmtDateTime(r.answered_at)}
            >{fmtTime(r.answered_at)}</td>
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
                      <!-- Full question + answer — the row above clamps both (line-clamp-2); here we
                           show them in full, below the leg header and above the Judge table, so long
                           questions/answers are readable without truncation. Question is the same
                           across legs; the answer is this leg's. -->
                      <div class="grid gap-1.5 text-xs leading-5">
                        <div class="flex flex-wrap gap-2">
                          <span class="min-w-[64px] text-muted-foreground">Question</span>
                          <span class="flex-1 whitespace-pre-wrap text-foreground">{@render hl(r.question)}</span>
                        </div>
                        <div class="flex flex-wrap gap-2">
                          <span class="min-w-[64px] text-muted-foreground">Answer</span>
                          {#if leg.answer}
                            <span class="flex-1 whitespace-pre-wrap text-foreground">{@render hl(leg.answer)}</span>
                          {:else}
                            <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
                          {/if}
                        </div>
                      </div>
                      <!-- Judge — its own collapsible colored section (matches the recalled-memory
                           sections below): verdict + recall sufficiency + grounded + reason + the
                           recalled line(s) the judge quoted (evidence). Recall + evidence are
                           memory-only (knowledge legs pass no context to the judge). -->
                      {#if leg.mark || leg.reason}
                        <details open class="overflow-hidden rounded-md border">
                          <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
                            Judge
                          </summary>
                          <div class="grid gap-2 border-t px-2.5 py-2 text-xs leading-5">
                            <div class="flex flex-wrap items-center gap-2">
                              <span class="min-w-[64px] text-muted-foreground">Verdict</span>
                              {#if leg.mark}
                                <Badge variant={markVariant(leg.mark)} class="font-mono" title={markTitle(leg.mark)}>{leg.mark} {markLabel(leg.mark)}</Badge>
                              {:else}
                                <span class="text-muted-foreground">—</span>
                              {/if}
                            </div>
                            {#if mode === 'recall'}
                              <div class="flex flex-wrap items-center gap-2">
                                <span class="min-w-[64px] text-muted-foreground">Recall</span>
                                {#if leg.recall_sufficient === false}
                                  <Badge variant="destructive" title="The recalled context did NOT contain what was needed — a recall miss, not an answering miss.">recall miss</Badge>
                                {:else}
                                  <Badge variant="success" title="The recalled facts/entities/episodes contained what was needed to answer.">sufficient</Badge>
                                {/if}
                              </div>
                            {/if}
                            <div class="flex flex-wrap items-center gap-2">
                              <span class="min-w-[64px] text-muted-foreground">Grounded</span>
                              {#if leg.grounded === false}
                                <Badge variant="warning" title="The answer was not grounded in the provided context.">ungrounded</Badge>
                              {:else}
                                <Badge variant="success" title="The answer is supported by the provided context.">grounded</Badge>
                              {/if}
                            </div>
                            {#if leg.reason}
                              <div class="flex flex-wrap gap-2">
                                <span class="min-w-[64px] text-muted-foreground">Reason</span>
                                <span class="flex-1 text-foreground">{@render hl(leg.reason)}</span>
                              </div>
                            {/if}
                            {#if mode === 'recall'}
                              <div class="flex flex-wrap gap-2">
                                <span class="min-w-[64px] text-muted-foreground">Evidence</span>
                                {#if leg.evidence}
                                  <span class="flex-1 whitespace-pre-wrap border-l-2 border-sky-400 bg-muted/40 px-2 py-1 font-mono text-[11px] leading-5 dark:border-sky-500">{@render hl(leg.evidence)}</span>
                                {:else}
                                  <span class="italic text-muted-foreground">— none quoted</span>
                                {/if}
                              </div>
                            {/if}
                          </div>
                        </details>
                      {/if}
                      <!-- Evidence recall (memory/recall leg, LoCoMo corpora): the gold evidence
                           episodes for this question and which the recall covered. Below the Judge
                           section, above the recalled memories. -->
                      {#if mode === 'recall' && r.evidence_recall && r.evidence_recall.total > 0}
                        {@render evidenceSection(r.evidence_recall)}
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
          {/if}
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

<!-- Evidence recall (LoCoMo): the gold evidence episodes for the question, each marked matched or
     missed against the recalled context. Own collapsible section (indigo header) below the Judge
     section. Header carries the X/Y count; per-row badges show matched/missed + how (kind). -->
{#snippet evidenceSection(ev: EvidenceRecall)}
  <details open class="overflow-hidden rounded-md border">
    <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide bg-indigo-100 text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200">
      Evidence recall ({ev.matched}/{ev.total})
    </summary>
    <div class="overflow-x-auto border-t">
      <table class="w-full border-collapse font-sans text-xs">
        <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th class="px-2 py-1 text-left">Status</th>
            <th class="px-2 py-1 text-left">Evidence</th>
            <th class="px-2 py-1 text-left">When</th>
            <th class="px-2 py-1 text-left">Via</th>
            <th class="px-2 py-1 text-right">Score</th>
          </tr>
        </thead>
        <tbody>
          {#each ev.items as it, i (it.episode_id || i)}
            <tr class="border-t align-top">
              <td class="whitespace-nowrap px-2 py-1">
                {#if it.matched}
                  <Badge variant="success">matched</Badge>
                {:else}
                  <Badge variant="destructive">missed</Badge>
                {/if}
              </td>
              <td class="max-w-[32rem] px-2 py-1">
                <!-- dia/short id (monospace) over the episode text snippet; speaker prefixed. -->
                <span class="font-mono text-[11px] text-muted-foreground">{@render hlR(it.dia_id || it.short_id || it.episode_id)}</span>
                {#if it.text}
                  <span class="line-clamp-3" title={it.text}>{#if it.speaker}<span class="font-semibold">{@render hlR(it.speaker)}:</span> {/if}{@render hlR(it.text)}</span>
                {:else}
                  <span class="block italic text-muted-foreground">(episode text unavailable)</span>
                {/if}
              </td>
              <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{it.when ? fmtEpisodeDate(it.when) : '—'}</td>
              <td class="px-2 py-1">
                {#if it.matched_via}<Badge variant="outline" class="font-sans normal-case">{it.matched_via}</Badge>{:else}<span class="text-muted-foreground">—</span>{/if}
              </td>
              <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">{it.score != null ? it.score.toFixed(3) : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </details>
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
            <span class="line-clamp-3" title={f.fact || f.memory}>{@render hlR(f.fact || f.memory)}</span>
          </td>
          <td class="px-2 py-1 font-mono text-[11px] text-muted-foreground">{#if f.name}{@render hlR(f.name)}{:else}—{/if}</td>
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
            {#if e.name}<span class="font-semibold">{@render hlR(e.name)}</span>{/if}
            <span class="line-clamp-2 text-muted-foreground" title={e.summary || e.memory}>{@render hlR(e.summary || e.memory)}</span>
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
            <span class="line-clamp-3" title={ep.memory}>{@render hlR(ep.memory)}</span>
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

<!-- Per-bucket × leg breakdown. Two visual groups per leg: the ANSWER-TYPE distribution (named,
     colored icons: Pass/Partial/Fail/Abstain) then the METRICS group (Recall Accuracy, Score x/y +
     %, Correct x/y + %), separated by a divider. A colored Total row sums all buckets. ``header``
     labels the first column; ``cols`` are the legs (memory = single ``recall``). -->
{#snippet breakdownTable(bc: Record<string, EvalCategoryStat>, cols: string[], header: string)}
  {@const multi = cols.length > 1}
  {@const totals = breakdownTotals(bc, cols)}
  {#snippet legHead()}
    {#each cols as mode (mode)}
      {#each MARK_GROUP_META as grp, gi (grp.key)}
        {@const Icon = grp.Icon}
        <th class="px-1.5 py-1 text-center {gi === 0 && multi ? 'border-l' : ''}">
          <span class="inline-flex items-center gap-1 {grp.cls}">
            <Icon size={12} aria-hidden="true" />{grp.name}
          </span>
        </th>
      {/each}
      <th class="border-l-2 border-border px-1.5 py-1 text-center" title="Recall Accuracy — the recalled facts/entities/episodes include the items required to answer correctly (of judged rows)">Recall&nbsp;Accuracy</th>
      <th class="px-1.5 py-1 text-center" title="Score — pass = 1 point, partial answer = ½ point, fail/abstain when an answer exists = 0 points">Score</th>
      <th class="px-1.5 py-1 text-center" title="Score % (of total)">Score&nbsp;%</th>
      <th class="px-1.5 py-1 text-center" title="Correct Answers — Pass = 1 point, anything else = 0 points (more restrictive than Score)">Correct&nbsp;Answers</th>
      <th class="px-1.5 py-1 text-center" title="Correct Answers % (of total)">Correct&nbsp;%</th>
      {#if hasEvidenceReport}
        <!-- Evidence recall (LoCoMo): gold-evidence episodes the recall covered, summed across the
             bucket, as matched/total + %. Memory single-leg only (hasEvidenceReport ⇒ isMemory). -->
        <th class="border-l-2 border-border px-1.5 py-1 text-center" title="Evidence recall — gold evidence episodes the recall covered (matched / total + %), summed across this bucket (LoCoMo corpora)">Evidence&nbsp;recall</th>
      {/if}
    {/each}
  {/snippet}
  {#snippet bdCells(st: EvalCategoryStat, flatCorrect: number, isTotal = false)}
    {@const tone = isTotal ? 'text-foreground font-semibold' : 'text-muted-foreground'}
    {#each cols as mode (mode)}
      {@const g = st.groups?.[mode] ?? { pass: 0, partial: 0, fail: 0, abstain: 0 }}
      {@const judged = g.pass + g.partial + g.fail + g.abstain}
      {@const correct = st.correct?.[mode] ?? 0}
      {@const score = st.score?.[mode] ?? 0}
      {@const recallOk = st.recall_ok?.[mode] ?? 0}
      {@const win = mode !== 'flat' && correct > flatCorrect}
      {@const winCls = win ? 'font-semibold text-emerald-600' : isTotal ? 'text-foreground font-semibold' : 'text-foreground'}
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone} {multi ? 'border-l' : ''}">{g.pass}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.partial}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.fail}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.abstain}</td>
      <td class="border-l-2 border-border px-1.5 py-1.5 text-center font-mono tabular-nums {tone}" title="{recallOk}/{judged} judged">{pct(recallOk, judged)}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{fmtScore(score)}/{st.total}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{pct(score, st.total)}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{correct}/{st.total}</td>
      <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {winCls}">{pct(correct, st.total)}</td>
      {#if hasEvidenceReport}
        {@const em = st.evidence_matched ?? 0}
        {@const et = st.evidence_total ?? 0}
        <td
          class="border-l-2 border-border px-1.5 py-1.5 text-center font-mono tabular-nums {tone}"
          title="{em}/{et} gold evidence episodes recalled across this {isTotal ? 'report' : 'bucket'}"
        >{#if et > 0}{em}/{et} · {pct(em, et)}{:else}—{/if}</td>
      {/if}
    {/each}
  {/snippet}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-sm">
      <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
        {#if multi}
          <!-- Leg-name grouping row above the per-leg sub-columns. -->
          <tr>
            <th class="px-2 py-1.5 text-left" rowspan="2">{header}</th>
            <th class="px-2 py-1.5 text-center" rowspan="2">Total</th>
            {#each cols as mode (mode)}
              <th class="border-l px-2 py-1 text-center" colspan="9">{legLabel(mode)}</th>
            {/each}
          </tr>
          <tr>{@render legHead()}</tr>
        {:else}
          <tr>
            <th class="px-2 py-1.5 text-left">{header}</th>
            <th class="px-2 py-1.5 text-center">Total</th>
            {@render legHead()}
          </tr>
        {/if}
      </thead>
      <tbody>
        {#each Object.entries(bc) as [cat, st] (cat)}
          <tr class="border-t">
            <td class="px-2 py-1.5">{cat}</td>
            <td class="px-2 py-1.5 text-center font-mono tabular-nums text-muted-foreground">{st.total}</td>
            {@render bdCells(st, st.correct?.flat ?? 0)}
          </tr>
        {/each}
        <!-- Totals across all buckets — distinct color, every value bold. -->
        <tr class="border-t-2 border-primary/40 bg-primary/10 font-semibold text-foreground">
          <td class="px-2 py-1.5">Total</td>
          <td class="px-2 py-1.5 text-center font-mono tabular-nums">{totals.total}</td>
          {@render bdCells(totals, totals.correct.flat ?? 0, true)}
        </tr>
      </tbody>
    </table>
  </div>
{/snippet}
