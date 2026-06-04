/**
 * L3 prototype (Phase 5e/5g) — controller for the Eval Batch section under the Ask tab.
 *
 * Responsibilities:
 *  - Setup form state (corpus + ingest / build_graph checkboxes + question checklist)
 *  - Triggering ``POST /knowledge/eval/run`` (returns run_id; eval runs in background)
 *  - Subscribing to the ``/knowledge/events`` SSE stream for live updates
 *  - Accumulating the live activity trail (``setupEvents``) + per-question rows
 *    (with FULL answers) so the terminal + expandable table render reactively
 *  - Surfacing the final PROCEED/PIVOT gate when ``completed`` lands
 *  - Cancelling an in-flight run
 *
 * Source of truth is SERVER-SIDE (``GET /knowledge/eval/state``), not
 * sessionStorage. On mount we subscribe (so an in-flight run keeps streaming)
 * and then hydrate from the server. This is what makes the panel:
 *   - survive navigation *mid-run* (the SSE alone has no backlog), and
 *   - show the SAME run on the Vite dev UI and the packaged admin UI (different
 *     origins → separate sessionStorage; the old client-only snapshot diverged).
 */
import {
  connectKnowledgeEvalEvents,
  type EvalCancelledPayload,
  type EvalCompletedPayload,
  type EvalFailedPayload,
  type EvalLeg,
  type EvalQuestionLeg,
  type EvalQuestionPayload,
  type EvalRunStateData,
  type EvalSetupProgressPayload,
  type EvalStartedPayload
} from '$lib/features/knowledge/shared/knowledge-events';
import {
  cancelKnowledgeEval,
  getKnowledgeEvalState,
  listEvalQuestions,
  runKnowledgeEval,
  type EvalQuestionItem
} from '$lib/api/knowledge';

/** Max questions selectable in the checklist (cap, per the design). */
export const EVAL_MAX_SELECTED = 50;

/** All selectable legs, in canonical column order. */
export const EVAL_ALL_LEGS: EvalLeg[] = ['flat', 'graphiti', 'mix'];

/** Human label for a leg (column header / chip). */
export const EVAL_LEG_LABEL: Record<string, string> = {
  flat: 'Flat',
  graphiti: 'Graphiti',
  mix: 'Mix'
};
import { PREF_KEYS } from '$lib/preferences/keys';
import { readLocalBoolean, writeLocalBoolean } from '$lib/preferences/storage';

export type EvalStatus =
  | 'idle' // nothing has run yet (or the last run was cleared)
  | 'starting' // POST sent, waiting for the started event
  | 'running' // started event received, question events streaming
  | 'completed' // completed event received
  | 'failed' // failed event received OR transport error
  | 'cancelled'; // user cancelled the run

/** What we render per question — ``legs`` keyed by leg name (only the run's
 *  selected legs), full answers included for the expandable row. */
export type EvalRow = {
  index: number;
  total: number;
  id: string;
  category: string;
  subcategory: string;
  question: string;
  requires_graph: boolean;
  legs: Record<string, EvalQuestionLeg>;
  delta: string;
  // Scoring rubric (display-only): what answers are judged against. Empty
  // expected_fragments = negative-control (abstaining is the correct outcome).
  expected_fragments: string[];
  must_not_contain: string[];
};

function rowFromPayload(p: EvalQuestionPayload): EvalRow {
  return {
    index: p.index,
    total: p.total,
    id: p.id,
    category: p.category,
    subcategory: p.subcategory ?? '',
    question: p.question,
    requires_graph: p.requires_graph,
    legs: p.legs ?? {},
    delta: p.delta,
    expected_fragments: p.expected_fragments ?? [],
    must_not_contain: p.must_not_contain ?? []
  };
}

export function createKnowledgeEvalModel(deps: { setError: (message: string | null) => void }) {
  // Setup-form state — defaults off, but the user's last choice persists across
  // reloads via localStorage (mirrors the ingest tab's buildGraphAfter pattern).
  let ingestSynthetic = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, false));
  let buildGraph = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, false));

  // Corpus + checklist state. Default to the Adam temporal corpus (the new path);
  // 'synthetic' keeps the legacy .md L3 eval. The checklist + per-category results
  // only apply on the Adam path.
  let corpusSource = $state<'synthetic' | 'adam'>('adam');
  let questions = $state<EvalQuestionItem[]>([]);
  let questionsLoading = $state(false);
  let questionsError = $state<string | null>(null);
  // Selected question ids (capped at EVAL_MAX_SELECTED). Reassigned (new Set) on
  // every mutation so Svelte 5 tracks it. Empty = run ALL questions.
  let selected = $state<Set<string>>(new Set());

  // Selected legs to compare (flat/graphiti/mix). Default = all three. At least
  // one must stay selected; toggling the last one off is ignored. Stored as an
  // ordered array (canonical order) so the table columns are stable.
  let selectedModes = $state<EvalLeg[]>([...EVAL_ALL_LEGS]);
  // The legs the CURRENT run actually used (from the started/state event) — drives
  // the live table/summary columns, independent of the next run's selection.
  let runModes = $state<string[]>([...EVAL_ALL_LEGS]);

  function isModeSelected(mode: EvalLeg): boolean {
    return selectedModes.includes(mode);
  }

  function toggleMode(mode: EvalLeg) {
    if (selectedModes.includes(mode)) {
      if (selectedModes.length === 1) return; // keep at least one leg
      selectedModes = selectedModes.filter((m) => m !== mode);
    } else {
      // Re-insert in canonical order so columns don't reorder by click order.
      selectedModes = EVAL_ALL_LEGS.filter((m) => m === mode || selectedModes.includes(m));
    }
  }

  async function loadQuestions() {
    if (corpusSource !== 'adam') {
      questions = [];
      return;
    }
    questionsLoading = true;
    questionsError = null;
    try {
      const res = await listEvalQuestions('adam');
      questions = res.data.questions ?? [];
    } catch (err) {
      questionsError = err instanceof Error ? err.message : 'Failed to load questions.';
      questions = [];
    } finally {
      questionsLoading = false;
    }
  }

  function setCorpusSource(v: 'synthetic' | 'adam') {
    if (corpusSource === v) return;
    corpusSource = v;
    selected = new Set();
    if (v === 'adam') void loadQuestions();
    else questions = [];
  }

  function toggleQuestion(id: string) {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      if (next.size >= EVAL_MAX_SELECTED) return; // cap reached — ignore
      next.add(id);
    }
    selected = next;
  }

  /** Select/deselect a whole category's ids (respecting the cap on select). */
  function setCategorySelected(ids: string[], on: boolean) {
    const next = new Set(selected);
    if (on) {
      for (const id of ids) {
        if (next.size >= EVAL_MAX_SELECTED) break;
        next.add(id);
      }
    } else {
      for (const id of ids) next.delete(id);
    }
    selected = next;
  }

  function clearSelection() {
    selected = new Set();
  }

  // Run state — hydrated from the server on mount (see ``init``), then kept live
  // by the SSE handlers below. No sessionStorage: the server registry is the
  // single source of truth so navigation + cross-origin stay consistent.
  let status = $state<EvalStatus>('idle');
  let runId = $state<string | null>(null);
  let totalQuestions = $state(0);
  let rows = $state<EvalRow[]>([]);
  let summary = $state<EvalCompletedPayload | null>(null);
  let failureMessage = $state<string | null>(null);
  // Latest setup event (for the collapsed header summary).
  let setupPhase = $state<EvalSetupProgressPayload | null>(null);
  // Full setup activity trail (the live terminal renders this + rows).
  let setupEvents = $state<EvalSetupProgressPayload[]>([]);
  let cancelling = $state(false);

  // ONE EventSource for the controller's lifetime.
  let teardownEvents: (() => void) | null = null;

  function ensureSubscribed() {
    if (teardownEvents) return;
    teardownEvents = connectKnowledgeEvalEvents({
      onStarted: handleStarted,
      onSetupProgress: handleSetupProgress,
      onQuestion: handleQuestion,
      onCompleted: handleCompleted,
      onFailed: handleFailed,
      onCancelled: handleCancelled
    });
  }

  /** Mount hook: subscribe (so an already-running eval keeps streaming) then
   *  replay the server's run state. Subscribe-first avoids a gap; the hydrate's
   *  index-keyed upsert dedupes any event seen in the tiny overlap window. */
  async function init() {
    ensureSubscribed();
    await hydrateFromServer();
  }

  async function hydrateFromServer() {
    try {
      const res = await getKnowledgeEvalState();
      const state = res.data;
      if (!state) {
        // No run on the server (idle, or server restarted) — only reset if we're
        // not mid-start locally (don't clobber a run we just kicked off).
        if (status === 'idle') resetRunState();
        return;
      }
      applyServerState(state);
    } catch (err) {
      // Replay is best-effort — a failed hydrate just means no history to show;
      // live events still flow. Surface nothing (the panel isn't broken).
      console.warn('eval state hydrate failed', err);
    }
  }

  function applyServerState(state: EvalRunStateData) {
    runId = state.run_id;
    status = state.status;
    totalQuestions = state.total_questions;
    if (state.modes?.length) runModes = state.modes;
    setupEvents = state.setup_events ?? [];
    setupPhase = setupEvents.length > 0 ? setupEvents[setupEvents.length - 1] : null;
    rows = (state.rows ?? []).map(rowFromPayload).sort((a, b) => a.index - b.index);
    summary = state.summary;
    failureMessage = state.failure_message;
    cancelling = state.cancel_requested && state.status === 'running';
  }

  function resetRunState() {
    status = 'idle';
    runId = null;
    totalQuestions = 0;
    rows = [];
    summary = null;
    failureMessage = null;
    setupPhase = null;
    setupEvents = [];
    cancelling = false;
  }

  /** Called on component unmount; closes the SSE connection. */
  function teardown() {
    if (teardownEvents) {
      teardownEvents();
      teardownEvents = null;
    }
  }

  function isOurRun(payloadRunId: string): boolean {
    return runId !== null && payloadRunId === runId;
  }

  function handleStarted(p: EvalStartedPayload) {
    if (!isOurRun(p.run_id)) return;
    status = 'running';
    totalQuestions = p.total_questions;
    if (p.modes?.length) runModes = p.modes;
    setupPhase = null; // we're past setup once started fires
  }

  function handleSetupProgress(p: EvalSetupProgressPayload) {
    // Setup events fire during 'starting' (before started). Gate by run_id when
    // we know it, else accept while starting (run_id may not be set yet).
    if (p.run_id && runId && p.run_id !== runId) return;
    if (status !== 'starting' && status !== 'running') return;
    setupPhase = p;
    setupEvents = [...setupEvents, p];
  }

  function handleQuestion(p: EvalQuestionPayload) {
    if (p.run_id && runId && p.run_id !== runId) return;
    if (status !== 'running') return;
    const row = rowFromPayload(p);
    // Replace if the same index already exists (defensive against duplicate
    // delivery), else append. Keeps the table ordered by question index.
    const existingAt = rows.findIndex((r) => r.index === row.index);
    if (existingAt >= 0) {
      rows = rows.map((r, i) => (i === existingAt ? row : r));
    } else {
      rows = [...rows, row];
    }
  }

  function handleCompleted(p: EvalCompletedPayload) {
    if (!isOurRun(p.run_id)) return;
    summary = p;
    status = 'completed';
    cancelling = false;
  }

  function handleFailed(p: EvalFailedPayload) {
    if (!isOurRun(p.run_id)) return;
    failureMessage = p.error;
    status = 'failed';
    cancelling = false;
  }

  function handleCancelled(p: EvalCancelledPayload) {
    if (!isOurRun(p.run_id)) return;
    status = 'cancelled';
    cancelling = false;
  }

  async function start() {
    if (status === 'starting' || status === 'running') return;
    // Fresh slate every run — last run's table doesn't bleed into this one.
    rows = [];
    summary = null;
    failureMessage = null;
    setupPhase = null;
    setupEvents = [];
    cancelling = false;
    runId = null;
    totalQuestions = 0;
    status = 'starting';
    // Lock the table columns to this run's selection immediately (before the
    // started event echoes it back) so the live table renders the right columns.
    runModes = [...selectedModes];
    deps.setError(null);
    ensureSubscribed();

    try {
      const req: import('$lib/api/knowledge').EvalRunRequest = {
        ingest_synthetic: ingestSynthetic,
        build_graph: buildGraph,
        corpus_source: corpusSource,
        modes: [...selectedModes]
      };
      // Empty selection on the Adam path = run ALL questions.
      if (corpusSource === 'adam' && selected.size > 0) {
        req.question_ids = [...selected];
      }
      const res = await runKnowledgeEval(req);
      runId = res.data.run_id;
    } catch (err) {
      status = 'failed';
      failureMessage = err instanceof Error ? err.message : 'Failed to start eval run.';
      deps.setError(failureMessage);
    }
  }

  async function cancel() {
    if ((status !== 'running' && status !== 'starting') || cancelling) return;
    cancelling = true;
    try {
      await cancelKnowledgeEval(runId);
      // The terminal 'cancelled' event flips status; if it never arrives (e.g.
      // the run finished first), the completed/failed handler clears cancelling.
    } catch (err) {
      cancelling = false;
      deps.setError(err instanceof Error ? err.message : 'Failed to cancel eval run.');
    }
  }

  function clear() {
    if (status === 'starting' || status === 'running') return;
    resetRunState();
  }

  return {
    get ingestSynthetic() {
      return ingestSynthetic;
    },
    set ingestSynthetic(v: boolean) {
      ingestSynthetic = v;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, v);
    },
    get buildGraph() {
      return buildGraph;
    },
    set buildGraph(v: boolean) {
      buildGraph = v;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, v);
    },
    get status() {
      return status;
    },
    get runId() {
      return runId;
    },
    get totalQuestions() {
      return totalQuestions;
    },
    get rows() {
      return rows;
    },
    get summary() {
      return summary;
    },
    get failureMessage() {
      return failureMessage;
    },
    get setupPhase() {
      return setupPhase;
    },
    get setupEvents() {
      return setupEvents;
    },
    get cancelling() {
      return cancelling;
    },
    // Corpus + checklist surface.
    get corpusSource() {
      return corpusSource;
    },
    setCorpusSource,
    get questions() {
      return questions;
    },
    get questionsLoading() {
      return questionsLoading;
    },
    get questionsError() {
      return questionsError;
    },
    get selectedCount() {
      return selected.size;
    },
    isSelected: (id: string) => selected.has(id),
    toggleQuestion,
    setCategorySelected,
    clearSelection,
    // Leg selection + the current run's active legs (table/summary columns).
    get selectedModes() {
      return selectedModes;
    },
    get runModes() {
      return runModes;
    },
    isModeSelected,
    toggleMode,
    loadQuestions,
    init,
    start,
    cancel,
    clear,
    teardown
  };
}

export type KnowledgeEvalModel = ReturnType<typeof createKnowledgeEvalModel>;
