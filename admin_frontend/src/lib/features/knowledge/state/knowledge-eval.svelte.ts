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

/** Eval track — knowledge (document corpus) or memory (turn corpus). */
export type EvalTrack = 'knowledge' | 'memory';
import {
  cancelKnowledgeEval,
  getKnowledgeEvalState,
  listEvalCorpuses,
  listEvalQuestions,
  pickKnowledgeFolder,
  runKnowledgeEval,
  type EvalCorpus,
  type EvalQuestionItem
} from '$lib/api/knowledge';

/** All selectable legs, in canonical column order. */
export const EVAL_ALL_LEGS: EvalLeg[] = ['flat', 'graphiti'];

/** Human label for a leg (column header / chip). */
export const EVAL_LEG_LABEL: Record<string, string> = {
  flat: 'Flat',
  graphiti: 'Graphiti'
};
import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readLocalBoolean,
  readLocalString,
  writeLocalBoolean,
  writeLocalString
} from '$lib/preferences/storage';

export type EvalStatus =
  | 'idle' // nothing has run yet (or the last run was cleared)
  | 'starting' // POST sent, waiting for the started event
  | 'running' // started event received, question events streaming
  | 'completed' // completed event received
  | 'failed' // failed event received OR transport error
  | 'cancelled'; // user cancelled the run

/** What we render per question (unified across tracks). ``legs`` is keyed by leg name —
 *  flat/graphiti (knowledge) or a single ``recall`` (memory); each leg has the model answer,
 *  the judge mark (or ""), the judge reason, and (memory) the recalled facts. */
export type EvalRow = {
  index: number;
  total: number;
  id: string;
  category: string;
  subcategory: string;
  question: string;
  requires_graph: boolean;
  track: EvalTrack;
  legs: Record<string, EvalQuestionLeg>;
  delta: string;
  gold: string; // the ideal answer (shown as "Ideal")
  cost_usd: number; // whole-question cost (LLM + reranker), for the live running total
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
    track: p.track ?? 'knowledge',
    legs: p.legs ?? {},
    delta: p.delta ?? '0',
    gold: p.gold ?? '',
    cost_usd: p.cost_usd ?? 0
  };
}

export function createKnowledgeEvalModel(deps: { setError: (message: string | null) => void }) {
  // Setup-form state — defaults off, but the user's last choice persists across
  // reloads via localStorage (mirrors the ingest tab's buildGraphAfter pattern).
  let ingestSynthetic = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, false));
  let buildGraph = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, false));
  // Optional LLM judge step (grades the model's answer vs the ideal). Off = answers only.
  let judge = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeEvalJudge, false));

  // Eval track. Default to the memory track (the new capability). 'knowledge' is the
  // document/chunk eval. Each track scans its own corpuses from the chosen folder.
  let track = $state<EvalTrack>('memory');

  // Corpus picker — a folder (text + native pick, like Knowledge Add), a scanned corpus
  // list, and the chosen corpus. Folder persists across reloads.
  let folder = $state<string>(localStorage.getItem(PREF_KEYS.knowledgeEvalFolder) ?? '');
  let corpuses = $state<EvalCorpus[]>([]);
  let corpusesLoading = $state(false);
  let corpusesError = $state<string | null>(null);
  let pickingFolder = $state(false);
  let selectedCorpusId = $state<string>('');

  // Question bank of the chosen corpus.
  let questions = $state<EvalQuestionItem[]>([]);
  let questionsLoading = $state(false);
  let questionsError = $state<string | null>(null);
  // Selected question ids — explicit; NO cap, and an empty set blocks the run.
  let selected = $state<Set<string>>(new Set());

  // Selected legs to compare (flat/graphiti, knowledge only). Default = both; one must stay.
  let selectedModes = $state<EvalLeg[]>([...EVAL_ALL_LEGS]);
  // The legs the CURRENT run actually used (started/state event) — drives table columns.
  let runModes = $state<string[]>([...EVAL_ALL_LEGS]);

  const selectedCorpus = (): EvalCorpus | null =>
    corpuses.find((c) => c.id === selectedCorpusId) ?? null;

  // Per-track last-selected corpus (localStorage). Survives a fresh page load so the
  // user lands back on the corpus they were working with — if it's still in the
  // scanned list; otherwise we fall back to the first corpus (see scanCorpuses).
  function readCorpusPref(t: EvalTrack): string {
    try {
      const raw = readLocalString(PREF_KEYS.knowledgeEvalCorpus);
      if (!raw) return '';
      return (JSON.parse(raw) as Partial<Record<EvalTrack, string>>)[t] ?? '';
    } catch {
      return '';
    }
  }
  function writeCorpusPref(t: EvalTrack, id: string) {
    let map: Partial<Record<EvalTrack, string>> = {};
    try {
      const raw = readLocalString(PREF_KEYS.knowledgeEvalCorpus);
      if (raw) map = JSON.parse(raw) as Partial<Record<EvalTrack, string>>;
    } catch {
      map = {};
    }
    if (id) map[t] = id;
    else delete map[t];
    writeLocalString(PREF_KEYS.knowledgeEvalCorpus, JSON.stringify(map));
  }

  function isModeSelected(mode: EvalLeg): boolean {
    return selectedModes.includes(mode);
  }

  function toggleMode(mode: EvalLeg) {
    if (selectedModes.includes(mode)) {
      if (selectedModes.length === 1) return; // keep at least one leg
      selectedModes = selectedModes.filter((m) => m !== mode);
    } else {
      selectedModes = EVAL_ALL_LEGS.filter((m) => m === mode || selectedModes.includes(m));
    }
  }

  /** Scan the chosen folder for this track's corpuses; auto-select the first. */
  async function scanCorpuses() {
    corpusesLoading = true;
    corpusesError = null;
    try {
      const res = await listEvalCorpuses(track, folder.trim());
      corpuses = res.data.corpuses ?? [];
      // Keep the folder the server resolved (so the default eval/ path shows in the field).
      if (!folder.trim() && res.data.folder) folder = res.data.folder;
      // Prefer the current in-session selection, else the persisted one (fresh load),
      // else the first corpus. Only ids that still exist in the scanned list survive.
      const desired = selectedCorpusId || readCorpusPref(track);
      const keep = corpuses.find((c) => c.id === desired);
      selectedCorpusId = keep ? keep.id : (corpuses[0]?.id ?? '');
      if (selectedCorpusId) writeCorpusPref(track, selectedCorpusId);
      await loadQuestions();
    } catch (err) {
      corpusesError = err instanceof Error ? err.message : 'Failed to scan corpuses.';
      corpuses = [];
      selectedCorpusId = '';
      questions = [];
    } finally {
      corpusesLoading = false;
    }
  }

  async function browseFolder() {
    pickingFolder = true;
    deps.setError(null);
    try {
      const res = await pickKnowledgeFolder(folder.trim() || undefined);
      if (res.data.folder) {
        setFolder(res.data.folder);
        await scanCorpuses();
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Folder picker failed.');
    } finally {
      pickingFolder = false;
    }
  }

  function setFolder(v: string) {
    folder = v;
    localStorage.setItem(PREF_KEYS.knowledgeEvalFolder, v);
  }

  /** Load the chosen corpus's question bank; clears the prior selection. */
  async function loadQuestions() {
    selected = new Set();
    const corpus = selectedCorpus();
    if (!corpus || !corpus.questions_path) {
      questions = [];
      questionsError = corpus && !corpus.questions_path
        ? `No question bank (${corpus.id}.questions.yaml) found beside this corpus.`
        : null;
      return;
    }
    questionsLoading = true;
    questionsError = null;
    try {
      const res = await listEvalQuestions(corpus.questions_path);
      questions = res.data.questions ?? [];
    } catch (err) {
      questionsError = err instanceof Error ? err.message : 'Failed to load questions.';
      questions = [];
    } finally {
      questionsLoading = false;
    }
  }

  function selectCorpus(id: string) {
    if (selectedCorpusId === id) return;
    selectedCorpusId = id;
    writeCorpusPref(track, id);
    void loadQuestions();
  }

  function setTrack(v: EvalTrack) {
    if (track === v) return;
    track = v;
    selectedCorpusId = '';
    selected = new Set();
    questions = [];
    void scanCorpuses();
  }

  function toggleQuestion(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  /** Select/deselect a whole category's ids (no cap). */
  function setCategorySelected(ids: string[], on: boolean) {
    const next = new Set(selected);
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    selected = next;
  }

  function clearSelection() {
    selected = new Set();
  }

  /** Select every question in the loaded bank (no cap). */
  function selectAll() {
    selected = new Set(questions.map((q) => q.id));
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
   *  index-keyed upsert dedupes any event seen in the tiny overlap window.
   *
   *  ``initialTrack`` lets the host page start the model on the persisted /
   *  deep-linked track tab. We set it WITHOUT a scan here (unlike ``setTrack``)
   *  so init's own ``scanCorpuses`` is the single scan for the right track.
   *  ``hydrateFromServer`` may still override the track if a run is in flight. */
  async function init(initialTrack?: EvalTrack) {
    if (initialTrack && initialTrack !== track) {
      track = initialTrack;
      selectedCorpusId = '';
      selected = new Set();
      questions = [];
    }
    ensureSubscribed();
    await hydrateFromServer();
    // Populate the corpus picker for the current track (cheap; independent of any run).
    await scanCorpuses();
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
    // Adopt the run's track ONLY while it's live (starting/running) so navigating
    // in mid-run — even from a different origin with its own tab persistence —
    // snaps to the running track. A terminal run must NOT hijack the user's
    // selected / deep-linked track tab (the page owns the track now).
    if (state.track && (state.status === 'starting' || state.status === 'running')) {
      track = state.track;
    }
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
    const corpus = selectedCorpus();
    // Guard: explicit corpus + explicit, non-empty question selection (no "run all").
    if (!corpus) {
      deps.setError('Pick a corpus before running the eval.');
      return;
    }
    if (selected.size === 0) {
      deps.setError('Select at least one question to run.');
      return;
    }
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
    // Lock the table columns to this run's selection immediately (before the started
    // event echoes it back). Memory = a single recall leg; knowledge = the picked legs.
    runModes = track === 'memory' ? ['recall'] : [...selectedModes];
    deps.setError(null);
    ensureSubscribed();

    try {
      const req: import('$lib/api/knowledge').EvalRunRequest = {
        track,
        corpus_id: corpus.id,
        corpus_path: corpus.corpus_path,
        questions_path: corpus.questions_path,
        ingest_synthetic: ingestSynthetic,
        judge,
        question_ids: [...selected]
      };
      if (track === 'knowledge') {
        req.build_graph = buildGraph;
        req.modes = [...selectedModes];
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
    get judge() {
      return judge;
    },
    set judge(v: boolean) {
      judge = v;
      writeLocalBoolean(PREF_KEYS.knowledgeEvalJudge, v);
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
    // Track surface.
    get track() {
      return track;
    },
    setTrack,
    // Corpus picker surface.
    get folder() {
      return folder;
    },
    setFolder,
    browseFolder,
    scanCorpuses,
    get pickingFolder() {
      return pickingFolder;
    },
    get corpuses() {
      return corpuses;
    },
    get corpusesLoading() {
      return corpusesLoading;
    },
    get corpusesError() {
      return corpusesError;
    },
    get selectedCorpusId() {
      return selectedCorpusId;
    },
    get selectedCorpus() {
      return selectedCorpus();
    },
    selectCorpus,
    // Checklist surface.
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
    selectAll,
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
    // Re-pull the server-side run state. Used when the tab regains focus: the knowledge
    // SSE is paused on hidden tabs (to free the connection pool), so any events that fired
    // while backgrounded were missed — re-hydrating snaps the panel back to server truth.
    resync: hydrateFromServer,
    start,
    cancel,
    clear,
    teardown
  };
}

export type KnowledgeEvalModel = ReturnType<typeof createKnowledgeEvalModel>;
