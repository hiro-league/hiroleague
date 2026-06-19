/**
 * Eval model — the composition root for the Eval panel. It is a THIN facade: it instantiates the
 * four sub-controllers (run lifecycle, setup form, corpus picker, memory results), owns only the
 * cross-cutting state + orchestration (the active track, the question-run `start`, corpus selection,
 * init/teardown), and wires the seams between the sub-controllers. The flat public surface is
 * preserved so the panes consume `eval_.<field>` exactly as before.
 *
 * Source of truth for the run is SERVER-SIDE (``GET /knowledge/eval/state``), not sessionStorage:
 * on mount we subscribe (so an in-flight run keeps streaming) then hydrate from the server, which
 * makes the panel survive navigation mid-run and show the SAME run across origins (Vite vs packaged).
 */
import { runKnowledgeEval } from '$lib/api/knowledge';
import { buildEvalRunRequest } from '$lib/features/eval/shared/eval-request';
import { EVAL_ALL_LEGS } from '$lib/features/eval/shared/eval-legs';
import type { EvalTrack } from '$lib/features/eval/shared/eval-row';
import { createEvalRunController } from '$lib/features/eval/state/eval-run.svelte';
import { createEvalSetup } from '$lib/features/eval/state/eval-setup.svelte';
import { createEvalCorpusPicker } from '$lib/features/eval/state/eval-corpus-picker.svelte';
import { createEvalResults } from '$lib/features/eval/state/eval-results.svelte';

// Re-export the leg constants (definition lives in the leaf `eval-legs` module to avoid a circular
// import with the setup sub-controller) + the core value types, so existing consumers keep
// importing them from the model (stable public surface).
export { EVAL_ALL_LEGS, EVAL_LEG_LABEL } from '$lib/features/eval/shared/eval-legs';
export type { EvalTrack, EvalStatus, EvalRow } from '$lib/features/eval/shared/eval-row';

export function createEvalModel(deps: { setError: (message: string | null) => void }) {
  // Eval track. Default to the memory track (the new capability). 'knowledge' is the
  // document/chunk eval. Each track scans its own corpuses from the chosen folder.
  let track = $state<EvalTrack>('memory');

  // Run lifecycle + SSE live in their own controller (the run state machine, server hydrate, and
  // the one EventSource). It reads the active track and notifies us on terminal events / after
  // hydrate through this narrow seam; the model drives it from start / clear / loadResults.
  const run = createEvalRunController(
    {
      setError: deps.setError,
      getTrack: () => track,
      // applyServerState adopts the server's track only while a run is live (mid-run navigation).
      setTrackFromServer: (t) => (track = t),
      onTerminal: (kind) => {
        // Memory persists every question that finished, so reconcile the table to the FULL merged
        // on-disk snapshot. Knowledge has no persisted results → nothing to reconcile.
        if (track !== 'memory') return;
        if (kind === 'completed') {
          // The run upserted its questions to disk; also advance the episode window past the batch
          // just ingested so a chunked build "just works".
          setup.advanceEpisodeWindow();
          void results.loadResults(true);
        } else if (kind === 'failed') {
          // Refresh badges only (questions that completed before the failure were saved); keep the
          // failure banner — don't let the snapshot view overwrite it.
          void results.loadResults(false);
        } else {
          // Cancel still saved every question that finished — show the merged snapshot.
          void results.loadResults(true);
        }
      },
      afterHydrate: () => {
        // applyServerState replays only the server's LAST RUN; on the memory track a subset run is
        // a single category, so reconcile to the full on-disk snapshot whenever a corpus is already
        // selected (the resync path). loadResults guards live runs, so a mid-run resync still lets
        // the stream own the table.
        if (track === 'memory' && corpus.selectedCorpusId) void results.loadResults(true);
      }
    },
    { initialModes: [...EVAL_ALL_LEGS] }
  );

  // Setup form (run options + persistence). Reads the corpus/track/run through accessors.
  const setup = createEvalSetup({
    getTrack: () => track,
    getSelectedCorpus: () => corpus.selectedCorpus,
    getSelectedCorpusId: () => corpus.selectedCorpusId,
    getSetupEvents: () => run.setupEvents
  });

  // Memory-only saved-results surface (coverage maps, ingested ranges, benchmark overview, Clear).
  const results = createEvalResults({
    getTrack: () => track,
    getSelectedCorpus: () => corpus.selectedCorpus,
    getSelectedBenchmarkId: () => corpus.selectedBenchmarkId,
    getFolder: () => corpus.folder,
    setError: deps.setError,
    run
  });

  // Track-agnostic corpus context (folder/scan, corpus + benchmark, question bank + selection,
  // episode transcript). On every corpus resolve it restores the per-corpus setup and reloads
  // the saved results, via the seams below.
  const corpus = createEvalCorpusPicker({
    getTrack: () => track,
    setError: deps.setError,
    onCorpusResolved: () => {
      setup.restoreAnswerPrompt(corpus.selectedCorpusId);
      setup.applyRebuildDefaultForCorpus();
    },
    reloadResults: () => void results.loadResults()
  });

  /** Switch the eval track — reset the corpus picker, setup answer-prompt, run, and saved maps,
   *  then rescan the new track's corpuses (which repopulates the bank + results). */
  function setTrack(v: EvalTrack) {
    if (track === v) return;
    track = v;
    corpus.resetForTrack();
    setup.clearAnswerPrompt();
    run.resetRunState();
    results.resetSaved();
    void corpus.scanCorpuses();
  }

  /** Select a corpus. Memory results are PERSISTED per corpus, so switching loses nothing — reset
   *  the live view silently. Knowledge results aren't persisted, so confirm before abandoning a
   *  completed/failed run (a fresh/idle panel switches without a prompt; Cancel aborts the switch).
   *  Then commit the id, restore the per-corpus setup, and reload the bank + results. */
  function selectCorpus(id: string) {
    if (corpus.selectedCorpusId === id) return;
    if (track === 'memory') {
      run.resetRunState();
    } else {
      const hasResults = run.rows.length > 0 || run.summary !== null || run.failureMessage !== null;
      if (hasResults && run.status !== 'starting' && run.status !== 'running') {
        const ok = confirm('Switching corpus will clear the previous run’s results. Continue?');
        if (!ok) return;
        run.resetRunState();
      }
    }
    corpus.setSelectedCorpusId(id);
    setup.restoreAnswerPrompt(id);
    setup.applyRebuildDefaultForCorpus();
    void corpus.loadQuestions();
  }

  /** Switch benchmark → select that benchmark's first corpus (routes through selectCorpus so the
   *  question bank, answer-prompt, and Rebuild-graph default all refresh as on any corpus change). */
  function selectBenchmark(id: string) {
    if (corpus.selectedBenchmarkId === id) return;
    const first = corpus.corpuses.find((c) => c.benchmark === id);
    if (first) selectCorpus(first.id);
  }

  /** Mount hook: subscribe (so an already-running eval keeps streaming) then replay the server's
   *  run state. ``initialTrack`` lets the host page start on the persisted / deep-linked track tab;
   *  we set it WITHOUT a scan here (unlike ``setTrack``) so init's own ``scanCorpuses`` is the single
   *  scan for the right track. ``hydrateFromServer`` may still override the track if a run is live. */
  async function init(initialTrack?: EvalTrack) {
    if (initialTrack && initialTrack !== track) {
      track = initialTrack;
      corpus.resetForTrack();
    }
    run.ensureSubscribed();
    await run.hydrateFromServer();
    // Populate the corpus picker for the current track (cheap; independent of any run).
    await corpus.scanCorpuses();
  }

  /** Launch a run. ``intent`` splits the old single Run into the two explicit UI actions:
   *   - ``'ingest'``  — ingest/remember the corpus (+ build/clear per the ingestion options), with
   *     NO questions (a setup-only batch). This is how the graph gets built (in monitored chunks).
   *   - ``'questions'`` — answer the SELECTED questions against the EXISTING graph (never ingests),
   *     so a question subset re-runs without rebuilding. */
  async function start(intent: 'ingest' | 'questions' = 'questions') {
    if (run.status === 'starting' || run.status === 'running') return;
    const selectedCorpus = corpus.selectedCorpus;
    if (!selectedCorpus) {
      deps.setError('Pick a corpus before running the eval.');
      return;
    }
    const ingesting = intent === 'ingest';
    // Eval needs an explicit, non-empty question selection (no "run all"); Ingest needs none.
    if (!ingesting && corpus.selectedCount === 0) {
      deps.setError('Select at least one question to evaluate.');
      return;
    }
    deps.setError(null);
    // Fresh-slate the run state and lock the table columns to this run's selection (memory = a
    // single recall leg; knowledge = the picked legs), then connect the SSE.
    run.beginStarting(track === 'memory' ? ['recall'] : [...setup.selectedModes]);

    try {
      const req = buildEvalRunRequest({
        track,
        corpus: selectedCorpus,
        ingesting,
        judge: setup.judge,
        selectedIds: corpus.selectedIds,
        buildGraph: setup.buildGraph,
        selectedModes: setup.selectedModes,
        clearBefore: setup.clearBefore,
        episodeFrom: setup.episodeFrom,
        episodeTo: setup.episodeTo,
        questionConcurrency: setup.questionConcurrency,
        answerPromptId: setup.answerPromptId
      });
      const res = await runKnowledgeEval(req);
      run.setRunId(res.data.run_id);
      // Auto-disarm the Clear Graph wipe as soon as an ingest run is accepted: the next batch must
      // NOT silently wipe the graph we just built. The flag is per-run; users opt in again per wipe.
      if (track === 'memory' && ingesting && setup.clearBefore) setup.disarmClearBefore();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start eval run.';
      run.markFailed(message);
      deps.setError(message);
    }
  }

  /** Clear the panel. Memory: DELETE the corpus's saved results from disk (results-only — ingested
   *  memory is untouched), then reset the view. Knowledge: client-only reset (results aren't
   *  persisted). A failed disk delete aborts before the view reset (keeps the saved snapshot). */
  async function clear() {
    if (run.status === 'starting' || run.status === 'running') return;
    const ok = await results.clearSavedResults();
    if (!ok) return;
    run.resetRunState();
  }

  return {
    // --- Setup form (run options) ---------------------------------------------------------------
    get ingestSynthetic() {
      return setup.ingestSynthetic;
    },
    set ingestSynthetic(v: boolean) {
      setup.ingestSynthetic = v;
    },
    get buildGraph() {
      return setup.buildGraph;
    },
    set buildGraph(v: boolean) {
      setup.buildGraph = v;
    },
    get clearBefore() {
      return setup.clearBefore;
    },
    set clearBefore(v: boolean) {
      setup.clearBefore = v;
    },
    get episodeFrom() {
      return setup.episodeFrom;
    },
    set episodeFrom(v: number) {
      setup.episodeFrom = v;
    },
    get episodeTo() {
      return setup.episodeTo;
    },
    set episodeTo(v: number) {
      setup.episodeTo = v;
    },
    get selectedCorpusHasGraph() {
      return setup.selectedCorpusHasGraph;
    },
    get rebuildChecked() {
      return setup.rebuildChecked;
    },
    get judge() {
      return setup.judge;
    },
    set judge(v: boolean) {
      setup.judge = v;
    },
    get answerPromptId() {
      return setup.answerPromptId;
    },
    set answerPromptId(v: string) {
      setup.answerPromptId = v;
    },
    get questionConcurrency() {
      return setup.questionConcurrency;
    },
    set questionConcurrency(v: number) {
      setup.questionConcurrency = v;
    },
    get questionConcurrencyMax() {
      return setup.questionConcurrencyMax;
    },
    // Leg selection + the current run's active legs (table/summary columns).
    get selectedModes() {
      return setup.selectedModes;
    },
    isModeSelected: setup.isModeSelected,
    toggleMode: setup.toggleMode,

    // --- Run lifecycle (delegated to the run controller) ----------------------------------------
    get status() {
      return run.status;
    },
    get runId() {
      return run.runId;
    },
    get totalQuestions() {
      return run.totalQuestions;
    },
    get rows() {
      return run.rows;
    },
    get summary() {
      return run.summary;
    },
    get ingestRunId() {
      return run.ingestRunId;
    },
    get failureMessage() {
      return run.failureMessage;
    },
    get setupPhase() {
      return run.setupPhase;
    },
    get setupEvents() {
      return run.setupEvents;
    },
    get cancelling() {
      return run.cancelling;
    },
    get runModes() {
      return run.runModes;
    },

    // --- Track ----------------------------------------------------------------------------------
    get track() {
      return track;
    },
    setTrack,

    // --- Corpus picker --------------------------------------------------------------------------
    get folder() {
      return corpus.folder;
    },
    setFolder: corpus.setFolder,
    browseFolder: corpus.browseFolder,
    scanCorpuses: corpus.scanCorpuses,
    get pickingFolder() {
      return corpus.pickingFolder;
    },
    get corpuses() {
      return corpus.corpuses;
    },
    get benchmarks() {
      return corpus.benchmarks;
    },
    get selectedBenchmarkId() {
      return corpus.selectedBenchmarkId;
    },
    get visibleCorpuses() {
      return corpus.visibleCorpuses;
    },
    selectBenchmark,
    get corpusesLoading() {
      return corpus.corpusesLoading;
    },
    get corpusesError() {
      return corpus.corpusesError;
    },
    get selectedCorpusId() {
      return corpus.selectedCorpusId;
    },
    get logDir() {
      return corpus.logDir;
    },
    get selectedCorpus() {
      return corpus.selectedCorpus;
    },
    selectCorpus,
    get questions() {
      return corpus.questions;
    },
    get questionsLoading() {
      return corpus.questionsLoading;
    },
    get questionsError() {
      return corpus.questionsError;
    },
    get corpusEpisodes() {
      return corpus.corpusEpisodes;
    },
    get corpusExtraction() {
      return corpus.corpusExtraction;
    },
    get corpusExtractionGroup() {
      return corpus.corpusExtractionGroup;
    },
    get corpusMeta() {
      return corpus.corpusMeta;
    },
    get corpusLoading() {
      return corpus.corpusLoading;
    },
    get corpusError() {
      return corpus.corpusError;
    },
    loadCorpus: corpus.loadCorpus,
    loadQuestions: corpus.loadQuestions,
    // Checklist selection.
    get selectedCount() {
      return corpus.selectedCount;
    },
    isSelected: corpus.isSelected,
    toggleQuestion: corpus.toggleQuestion,
    setCategorySelected: corpus.setCategorySelected,
    clearSelection: corpus.clearSelection,
    selectAll: corpus.selectAll,

    // --- Memory results (saved coverage + benchmark overview) -----------------------------------
    get benchmarkResults() {
      return results.benchmarkResults;
    },
    get benchmarkResultsLoading() {
      return results.benchmarkResultsLoading;
    },
    get benchmarkResultsError() {
      return results.benchmarkResultsError;
    },
    loadBenchmarkResults: results.loadBenchmarkResults,
    savedStatus: results.savedStatus,
    savedRecallSufficient: results.savedRecallSufficient,
    savedAnsweredAt: results.savedAnsweredAt,
    get savedCount() {
      return results.savedCount;
    },
    get ingested() {
      return results.ingested;
    },
    loadResults: results.loadResults,

    // --- Cross-cutting lifecycle ----------------------------------------------------------------
    init,
    // Re-pull the server-side run state (tab-refocus): the knowledge SSE is paused on hidden tabs,
    // so re-hydrating snaps the panel back to server truth after missed events.
    resync: run.hydrateFromServer,
    start,
    cancel: run.cancel,
    clear,
    teardown: run.teardown
  };
}

export type EvalModel = ReturnType<typeof createEvalModel>;
