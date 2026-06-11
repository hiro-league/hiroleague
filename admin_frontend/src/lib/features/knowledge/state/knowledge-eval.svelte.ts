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
  clearEvalResults,
  getEvalCorpus,
  getKnowledgeEvalState,
  listEvalCorpuses,
  listEvalQuestions,
  listEvalResults,
  pickKnowledgeFolder,
  runKnowledgeEval,
  type EvalCorpus,
  type EvalEpisode,
  type EvalIngestedRanges,
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
  difficulty: string; // authored difficulty (medium/hard/very_hard); '' when omitted
  question: string;
  requires_graph: boolean;
  track: EvalTrack;
  legs: Record<string, EvalQuestionLeg>;
  delta: string;
  gold: string; // the ideal answer (shown as "Ideal")
  cost_usd: number; // whole-question cost (LLM + reranker), for the live running total
  is_negative_control: boolean; // abstaining is the correct outcome (drives abstain-is-correct)
  answered_at: string; // ISO-8601 UTC timestamp this question finished evaluating ('' if unknown)
};

function rowFromPayload(p: EvalQuestionPayload): EvalRow {
  return {
    index: p.index,
    total: p.total,
    id: p.id,
    category: p.category,
    subcategory: p.subcategory ?? '',
    difficulty: p.difficulty ?? '',
    question: p.question,
    requires_graph: p.requires_graph,
    track: p.track ?? 'knowledge',
    legs: p.legs ?? {},
    delta: p.delta ?? '0',
    gold: p.gold ?? '',
    cost_usd: p.cost_usd ?? 0,
    is_negative_control: p.is_negative_control ?? false,
    answered_at: p.answered_at ?? ''
  };
}

/** Read a persisted non-negative integer setting, falling back when unset/invalid. */
function readEvalInt(key: string, fallback: number): number {
  const n = parseInt(readLocalString(key) ?? '', 10);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

export function createKnowledgeEvalModel(deps: { setError: (message: string | null) => void }) {
  // Setup-form state — defaults off, but the user's last choice persists across
  // reloads via localStorage (mirrors the ingest tab's buildGraphAfter pattern).
  let ingestSynthetic = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, false));
  let buildGraph = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, false));
  // Optional LLM judge step (grades the model's answer vs the ideal). Off = answers only.
  let judge = $state<boolean>(readLocalBoolean(PREF_KEYS.knowledgeEvalJudge, false));

  // Memory track — explicit graph wipe BEFORE remembering. Decoupled from `ingestSynthetic`
  // (Remember) so a corpus can be built across appended batches without each wiping the last.
  // NOT persisted: a reload must never silently re-arm a wipe — the user opts in per run.
  let clearBefore = $state<boolean>(false);
  // Memory track — remember-phase episode window as 1-based, INCLUSIVE episode numbers (what the
  // user actually counts: episode 1 is the first turn). `episodeFrom` ≥ 1; `episodeTo` of 0 means
  // "to the end" (no cap). Converted to the backend's 0-based offset/limit at send time. Persisted
  // so a manual batched build keeps its place across reloads (and auto-advances after each batch).
  let episodeFrom = $state<number>(Math.max(1, readEvalInt(PREF_KEYS.knowledgeEvalEpisodeFrom, 1)));
  let episodeTo = $state<number>(readEvalInt(PREF_KEYS.knowledgeEvalEpisodeTo, 50));

  // Eval track. Default to the memory track (the new capability). 'knowledge' is the
  // document/chunk eval. Each track scans its own corpuses from the chosen folder.
  let track = $state<EvalTrack>('memory');

  // Corpus picker — a folder (text + native pick, like Knowledge Add), a scanned corpus
  // list, and the chosen corpus. Folder persists across reloads.
  let folder = $state<string>(localStorage.getItem(PREF_KEYS.knowledgeEvalFolder) ?? '');
  let corpuses = $state<EvalCorpus[]>([]);
  // Absolute workspace ``logs/`` dir (ledger sidecar root) from the corpus scan. The "Copy for AI"
  // brief uses it to point an agent at retrieval_trace/ingest_trace/graph.log without searching.
  // '' until the first scan resolves (or if the workspace can't be resolved) → brief falls back
  // to relative paths. Workspace-global, so it survives track/corpus switches.
  let logDir = $state<string>('');
  let corpusesLoading = $state(false);
  let corpusesError = $state<string | null>(null);
  let pickingFolder = $state(false);
  let selectedCorpusId = $state<string>('');

  // Question bank of the chosen corpus.
  let questions = $state<EvalQuestionItem[]>([]);
  let questionsLoading = $state(false);
  let questionsError = $state<string | null>(null);

  // Corpus review (memory track only) — the chosen corpus's episodes rendered as a readable
  // transcript above the questions, plus light meta (count + date span) for the stats header.
  // Knowledge corpora are folders of .md docs, not episode turns, so this stays empty there.
  let corpusEpisodes = $state<EvalEpisode[]>([]);
  let corpusMeta = $state<{
    episode_count: number;
    first_timestamp: string;
    last_timestamp: string;
  } | null>(null);
  let corpusLoading = $state(false);
  let corpusError = $state<string | null>(null);
  // Selected question ids — explicit; NO cap, and an empty set blocks the run.
  let selected = $state<Set<string>>(new Set());

  // Memory track only: per-question SAVED status, keyed by question id, from the corpus's
  // persisted results on disk. Drives the checklist coverage badges (pass/partial/fail/
  // abstain, or '' when answered-but-judge-off; ABSENT id = not-run). Kept independent of
  // the live `rows` so badges reflect saved coverage even mid-run or after a Clear.
  let savedStatusById = $state<Record<string, string>>({});

  // Memory track: per-question SAVED recall-sufficiency (judge-reported) for the recall leg —
  // only set for JUDGED rows (mark present), so an entry's absence means "not judged / unknown".
  // Drives the Questions table's recall-sufficiency flag.
  let savedRecallSufficientById = $state<Record<string, boolean>>({});

  // Memory track: per-question SAVED eval timestamp (ISO-8601) — when each question last finished
  // evaluating. Drives the Questions table's "Time" column.
  let savedAnsweredAtById = $state<Record<string, string>>({});

  // Ingested-episode progress for the selected memory corpus (which turns are in the graph) —
  // drives the Corpus header's "ingested …" readout. Refreshed by loadResults; reset to empty on
  // the knowledge track, no corpus, or after a graph wipe (the server returns empty ranges then).
  const EMPTY_INGESTED: EvalIngestedRanges = { ranges: [], count: 0, batches: 0, cost_usd: 0 };
  let ingested = $state<EvalIngestedRanges>(EMPTY_INGESTED);

  // Selected legs to compare (flat/graphiti, knowledge only). Default = both; one must stay.
  let selectedModes = $state<EvalLeg[]>([...EVAL_ALL_LEGS]);
  // The legs the CURRENT run actually used (started/state event) — drives table columns.
  let runModes = $state<string[]>([...EVAL_ALL_LEGS]);

  const selectedCorpus = (): EvalCorpus | null =>
    corpuses.find((c) => c.id === selectedCorpusId) ?? null;

  /** Derive the "Rebuild graph" checkbox default from the selected corpus's graph state:
   *  OFF when a graph already exists (reuse it), ON when none exists (you must build one).
   *  The corpus's graph state wins over the persisted last-used value on every corpus change.
   *  The relevant flag differs by track — memory's "Rebuild graph" is `ingestSynthetic`
   *  (re-remember turns); knowledge's is `buildGraph` (re-ingest entity graph). We write
   *  through the same vars + localStorage keys the setters use, so the persisted value tracks. */
  function applyRebuildDefaultForCorpus() {
    const corpus = selectedCorpus();
    if (!corpus) return;
    const rebuild = !corpus.has_graph;
    if (track === 'memory') {
      ingestSynthetic = rebuild;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, rebuild);
    } else {
      buildGraph = rebuild;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, rebuild);
    }
  }

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
      // Keep the resolved logs/ dir if present; never clobber a good value with an empty one
      // (a degraded scan shouldn't wipe a path the brief already has).
      if (res.data.log_dir) logDir = res.data.log_dir;
      // Keep the folder the server resolved (so the default eval/ path shows in the field).
      if (!folder.trim() && res.data.folder) folder = res.data.folder;
      // Prefer the current in-session selection, else the persisted one (fresh load),
      // else the first corpus. Only ids that still exist in the scanned list survive.
      const desired = selectedCorpusId || readCorpusPref(track);
      const keep = corpuses.find((c) => c.id === desired);
      selectedCorpusId = keep ? keep.id : (corpuses[0]?.id ?? '');
      if (selectedCorpusId) writeCorpusPref(track, selectedCorpusId);
      // Auto-set "Rebuild graph" from the (re)selected corpus's graph state.
      applyRebuildDefaultForCorpus();
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

  /** Load the chosen corpus's episodes for the Corpus review panel (memory track only).
   *  Independent of the question bank, so it runs even when the bank is missing. Clears
   *  to empty on the knowledge track (its corpora are .md folders, not episode turns). */
  async function loadCorpus() {
    corpusEpisodes = [];
    corpusMeta = null;
    corpusError = null;
    if (track !== 'memory') return;
    const corpus = selectedCorpus();
    if (!corpus || !corpus.corpus_path) return;
    corpusLoading = true;
    try {
      const res = await getEvalCorpus(corpus.corpus_path);
      corpusEpisodes = res.data.episodes ?? [];
      corpusMeta = {
        episode_count: res.data.episode_count,
        first_timestamp: res.data.first_timestamp,
        last_timestamp: res.data.last_timestamp
      };
    } catch (err) {
      corpusError = err instanceof Error ? err.message : 'Failed to load corpus episodes.';
    } finally {
      corpusLoading = false;
    }
  }

  /** Load the chosen corpus's SAVED (merged) eval results from disk (memory track).
   *
   *  Two jobs:
   *   1. Always refresh `savedStatusById` so the checklist coverage badges are current.
   *   2. When no live run is in flight, show the merged snapshot in the Results table +
   *      summary — so picking a corpus immediately shows its latest accumulated results.
   *
   *  ``applyView=false`` (used after a FAILED run) refreshes only the badges and leaves the
   *  failure banner/status intact. Knowledge track has no persisted results → clears badges. */
  async function loadResults(applyView = true) {
    if (track !== 'memory') {
      savedStatusById = {};
      savedRecallSufficientById = {};
      savedAnsweredAtById = {};
      ingested = EMPTY_INGESTED;
      return;
    }
    const corpus = selectedCorpus();
    if (!corpus) {
      savedStatusById = {};
      savedRecallSufficientById = {};
      savedAnsweredAtById = {};
      ingested = EMPTY_INGESTED;
      return;
    }
    try {
      const res = await listEvalResults('memory', corpus.id, corpus.questions_path);
      const data = res.data;
      const map: Record<string, string> = {};
      const rsMap: Record<string, boolean> = {};
      const aaMap: Record<string, string> = {};
      for (const r of data.rows) {
        const leg = r.legs?.recall;
        map[r.id] = leg?.mark ?? '';
        // Recall-sufficiency is only meaningful once judged (mark present); default true.
        if (leg?.mark) rsMap[r.id] = leg.recall_sufficient ?? true;
        if (r.answered_at) aaMap[r.id] = r.answered_at;
      }
      savedStatusById = map;
      savedRecallSufficientById = rsMap;
      savedAnsweredAtById = aaMap;
      // Ingested-range readout always refreshes (independent of the view guards below), so the
      // Corpus header stays accurate even mid-run or after a failed run.
      ingested = data.ingested ?? EMPTY_INGESTED;
      if (!applyView) return;
      // The live stream owns the table while a run is in flight; don't clobber it.
      if (status === 'starting' || status === 'running') return;
      rows = data.rows.map(rowFromPayload).sort((a, b) => a.index - b.index);
      summary = data.summary;
      // Lock the table/fold leg columns to the snapshot's legs (memory = ['recall']).
      // Without this, runModes stays at the default flat/graphiti and the memory rows'
      // `recall` leg matches no column → expanded rows render empty (only the leg loop is
      // keyed by runModes). Fixes "reloaded results expand to nothing".
      runModes = data.summary?.modes?.length ? data.summary.modes : ['recall'];
      failureMessage = null;
      // A non-empty snapshot reads as a completed (saved) run; empty falls back to idle.
      status = rows.length > 0 ? 'completed' : 'idle';
    } catch (err) {
      // Saved results are best-effort enrichment — a failure just means no snapshot to show.
      console.warn('eval saved-results load failed', err);
    }
  }

  /** Load the chosen corpus's question bank; clears the prior selection. */
  async function loadQuestions() {
    // Refresh the Corpus review transcript alongside the bank — both follow the chosen
    // corpus, so every entry point (scan / select / reload) keeps them in sync.
    void loadCorpus();
    // Refresh saved results (badges + merged snapshot) for the chosen corpus, in step
    // with the bank. Memory only; a no-op clear on the knowledge track.
    void loadResults();
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
    if (track === 'memory') {
      // Memory results are PERSISTED per corpus, so switching loses nothing — reset the
      // live view silently; loadQuestions→loadResults then shows the new corpus's saved
      // snapshot. (No confirm prompt; that was for the old in-memory-only behaviour.)
      resetRunState();
    } else {
      // Knowledge results aren't persisted: a run's results belong to the corpus it ran
      // against, so switching abandons them. Confirm before wiping a completed/failed run
      // (a misclick shouldn't silently drop it); a fresh/idle panel switches without a
      // prompt. Cancel aborts the switch (the bound <select> re-asserts the old value).
      const hasResults = rows.length > 0 || summary !== null || failureMessage !== null;
      if (hasResults && status !== 'starting' && status !== 'running') {
        const ok = confirm('Switching corpus will clear the previous run’s results. Continue?');
        if (!ok) return;
        resetRunState();
      }
    }
    selectedCorpusId = id;
    writeCorpusPref(track, id);
    // Auto-set "Rebuild graph" from the newly chosen corpus's graph state.
    applyRebuildDefaultForCorpus();
    void loadQuestions();
  }

  function setTrack(v: EvalTrack) {
    if (track === v) return;
    track = v;
    selectedCorpusId = '';
    selected = new Set();
    questions = [];
    // Clear the displayed run/results too — otherwise the previous track's snapshot (e.g. a
    // memory corpus's saved results) bleeds into the new track's view until something replaces
    // it. scanCorpuses → loadQuestions → loadResults then repopulates for the new track.
    resetRunState();
    savedStatusById = {};
      savedRecallSufficientById = {};
      savedAnsweredAtById = {};
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
    // Memory: the run upserted its questions to disk — reconcile the table to the FULL
    // merged snapshot (the subset we just ran + everything previously saved).
    if (track === 'memory') {
      advanceEpisodeWindow();
      void loadResults(true);
    }
  }

  /** Auto-advance the From/To window past the batch just ingested, so a chunked build "just works"
   *  (run, run, run) without re-typing the range. Shifts BOTH ends by the actual episodes ingested
   *  (the `remember_done` setup event's count) to preserve the window width. No-op when this run
   *  didn't ingest (no remember_done) or ingested to the end (`to` = 0 stays open-ended). */
  function advanceEpisodeWindow() {
    let batch = 0;
    for (let i = setupEvents.length - 1; i >= 0; i--) {
      if (setupEvents[i].phase === 'remember_done') {
        batch = setupEvents[i].episode_count ?? 0;
        break;
      }
    }
    if (batch <= 0) return;
    episodeFrom = episodeFrom + batch;
    writeLocalString(PREF_KEYS.knowledgeEvalEpisodeFrom, String(episodeFrom));
    if (episodeTo > 0) {
      episodeTo = episodeTo + batch;
      writeLocalString(PREF_KEYS.knowledgeEvalEpisodeTo, String(episodeTo));
    }
  }

  function handleFailed(p: EvalFailedPayload) {
    if (!isOurRun(p.run_id)) return;
    failureMessage = p.error;
    status = 'failed';
    cancelling = false;
    // Refresh badges only (questions that completed before the failure were saved); keep
    // the failure banner — don't let the snapshot view overwrite it.
    if (track === 'memory') void loadResults(false);
  }

  function handleCancelled(p: EvalCancelledPayload) {
    if (!isOurRun(p.run_id)) return;
    status = 'cancelled';
    cancelling = false;
    // Cancel still saved every question that finished — show the merged snapshot.
    if (track === 'memory') void loadResults(true);
  }

  async function start() {
    if (status === 'starting' || status === 'running') return;
    const corpus = selectedCorpus();
    // Guard: explicit corpus + explicit, non-empty question selection (no "run all").
    if (!corpus) {
      deps.setError('Pick a corpus before running the eval.');
      return;
    }
    // Setup-only batches (memory: remember a range / clear, with no questions) are allowed —
    // that's how a large corpus gets built in monitored chunks before any recall.
    const setupOnly = track === 'memory' && (ingestSynthetic || clearBefore);
    if (selected.size === 0 && !setupOnly) {
      deps.setError('Select at least one question, or enable Ingest / Clear for a setup-only batch.');
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
      } else {
        // Memory track — explicit wipe + remember-phase episode window. Convert the user-facing
        // 1-based INCLUSIVE from/to to the backend's 0-based offset + count: offset = from-1;
        // count = to-from+1 (≥0). `to` of 0 = "to the end" → null count (remember every remaining
        // episode). This is the layer that kills the off-by-one — the user types real episode
        // numbers, never a 0-based index.
        req.clear_before = clearBefore;
        req.episode_offset = Math.max(0, episodeFrom - 1);
        req.episode_limit = episodeTo > 0 ? Math.max(0, episodeTo - episodeFrom + 1) : null;
      }
      const res = await runKnowledgeEval(req);
      runId = res.data.run_id;
      // Auto-disarm the Clear Graph wipe as soon as the run is accepted: the next batch
      // (e.g. ingest episodes 101–200 after this one ingested 1–100) must NOT silently
      // wipe the graph we just built. The flag is per-run; users opt in again per wipe.
      if (track === 'memory' && clearBefore) clearBefore = false;
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

  /** Clear the panel. Memory: DELETE the corpus's saved results from disk (results-only —
   *  ingested memory is untouched), then reset the view. Knowledge: client-only reset (its
   *  results aren't persisted). */
  async function clear() {
    if (status === 'starting' || status === 'running') return;
    if (track === 'memory') {
      const corpus = selectedCorpus();
      if (corpus) {
        try {
          await clearEvalResults('memory', corpus.id);
        } catch (err) {
          deps.setError(err instanceof Error ? err.message : 'Failed to clear saved results.');
          return;
        }
      }
      savedStatusById = {};
      savedRecallSufficientById = {};
      savedAnsweredAtById = {};
    }
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
    // Memory track — explicit "Clear graph first" (decoupled from Remember). Not persisted.
    get clearBefore() {
      return clearBefore;
    },
    set clearBefore(v: boolean) {
      clearBefore = v;
    },
    // Memory track — remember-phase episode window as 1-based INCLUSIVE episode numbers
    // (From episode ≥ 1; To = 0 ⇒ to the end). Converted to 0-based offset/count at send time.
    get episodeFrom() {
      return episodeFrom;
    },
    set episodeFrom(v: number) {
      episodeFrom = Number.isFinite(v) && v >= 1 ? Math.floor(v) : 1;
      writeLocalString(PREF_KEYS.knowledgeEvalEpisodeFrom, String(episodeFrom));
    },
    get episodeTo() {
      return episodeTo;
    },
    set episodeTo(v: number) {
      episodeTo = Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
      writeLocalString(PREF_KEYS.knowledgeEvalEpisodeTo, String(episodeTo));
    },
    // Whether the selected corpus already has a graph (drives the run-time wipe warning).
    get selectedCorpusHasGraph() {
      return selectedCorpus()?.has_graph ?? false;
    },
    // The track's active "Rebuild graph" flag — memory uses `ingestSynthetic`, knowledge `buildGraph`.
    get rebuildChecked() {
      return track === 'memory' ? ingestSynthetic : buildGraph;
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
    // The remember-phase ingest Graph Run id for the current run, if known — from the terminal
    // summary or the live 'remember_done' setup event. Null on a subset re-run (no ingest) or a
    // reloaded snapshot (no single ingest run). Drives the panel's "Ingest pipeline" button.
    get ingestRunId(): string | null {
      if (summary?.ingest_run_id) return summary.ingest_run_id;
      for (let i = setupEvents.length - 1; i >= 0; i--) {
        const id = setupEvents[i].ingest_run_id;
        if (id) return id;
      }
      return null;
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
    // Absolute workspace logs/ dir for the "Copy for AI" brief's ledger-file pointers.
    get logDir() {
      return logDir;
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
    // Corpus review surface (memory track) — episodes transcript + meta for the section above
    // the questions.
    get corpusEpisodes() {
      return corpusEpisodes;
    },
    get corpusMeta() {
      return corpusMeta;
    },
    get corpusLoading() {
      return corpusLoading;
    },
    get corpusError() {
      return corpusError;
    },
    loadCorpus,
    get selectedCount() {
      return selected.size;
    },
    isSelected: (id: string) => selected.has(id),
    // Saved (persisted) per-question status for the checklist coverage badges (memory).
    // Returns the judge mark glyph, '' (answered, judge off), or undefined (not run).
    savedStatus: (id: string): string | undefined => savedStatusById[id],
    // Saved recall-sufficiency (judge-reported) for the recall leg — undefined when not judged.
    savedRecallSufficient: (id: string): boolean | undefined => savedRecallSufficientById[id],
    // Saved eval timestamp (ISO-8601) for a question — '' / undefined when not yet run.
    savedAnsweredAt: (id: string): string | undefined => savedAnsweredAtById[id],
    get savedCount() {
      return Object.keys(savedStatusById).length;
    },
    // Ingested-episode progress for the selected memory corpus (drives the Corpus header readout).
    get ingested() {
      return ingested;
    },
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
    loadResults,
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
