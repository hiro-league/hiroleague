/**
 * Eval setup-form sub-controller — the run OPTIONS the Execute tab edits, plus their localStorage
 * round-trip. It owns only its own form state; everything it needs about the selected corpus, the
 * active track, or the live run arrives through the injected accessors (`EvalSetupDeps`), so it
 * stays decoupled from the corpus picker / run controller it sits beside under the model facade.
 */
import type { EvalLeg, EvalSetupProgressPayload } from '$lib/features/knowledge/shared/knowledge-events';
import type { EvalCorpus } from '$lib/api/knowledge';
import { PREF_KEYS } from '$lib/preferences/keys';
import { readLocalBoolean, writeLocalBoolean, writeLocalString } from '$lib/preferences/storage';
import { readAnswerPromptPref, readEvalInt, writeAnswerPromptPref } from '$lib/features/eval/shared/eval-prefs';
import { EVAL_ALL_LEGS } from '$lib/features/eval/shared/eval-legs';
import type { EvalTrack } from '$lib/features/eval/shared/eval-row';

/** Narrow seam to the sibling sub-controllers (corpus picker + run), injected by the facade. */
export type EvalSetupDeps = {
  getTrack: () => EvalTrack;
  getSelectedCorpus: () => EvalCorpus | null;
  getSelectedCorpusId: () => string;
  /** The live run's setup activity trail — read by `advanceEpisodeWindow` after a batch ingests. */
  getSetupEvents: () => EvalSetupProgressPayload[];
};

export function createEvalSetup(deps: EvalSetupDeps) {
  // Setup-form state — defaults off, but the user's last choice persists across reloads via
  // localStorage (mirrors the ingest tab's buildGraphAfter pattern).
  let ingestSynthetic = $state<boolean>(readLocalBoolean(PREF_KEYS.evalIngest, false));
  let buildGraph = $state<boolean>(readLocalBoolean(PREF_KEYS.evalBuildGraph, false));
  // Optional LLM judge step (grades the model's answer vs the ideal). Off = answers only.
  let judge = $state<boolean>(readLocalBoolean(PREF_KEYS.evalJudge, false));
  // Memory track — which named answer-prompt profile (graph.eval.answer_prompts) this run uses.
  // '' = the locked default profile. Sticky PER CORPUS (last-used), restored on corpus change.
  let answerPromptId = $state<string>('');
  // Memory track — max questions evaluated concurrently (1 = serial). Mirrors the server's
  // MAX_QUESTION_CONCURRENCY ceiling; the server clamps anyway, this just keeps the control honest.
  const QUESTION_CONCURRENCY_MAX = 8;
  let questionConcurrency = $state<number>(
    Math.min(QUESTION_CONCURRENCY_MAX, Math.max(1, readEvalInt(PREF_KEYS.evalQuestionConcurrency, 1)))
  );

  // Memory track — explicit graph wipe BEFORE remembering. Decoupled from `ingestSynthetic`
  // (Remember) so a corpus can be built across appended batches without each wiping the last.
  // NOT persisted: a reload must never silently re-arm a wipe — the user opts in per run.
  let clearBefore = $state<boolean>(false);
  // Memory track — remember-phase episode window as 1-based, INCLUSIVE episode numbers (what the
  // user actually counts: episode 1 is the first turn). `episodeFrom` ≥ 1; `episodeTo` of 0 means
  // "to the end" (no cap). Converted to the backend's 0-based offset/limit at send time. Persisted
  // so a manual batched build keeps its place across reloads (and auto-advances after each batch).
  let episodeFrom = $state<number>(Math.max(1, readEvalInt(PREF_KEYS.evalEpisodeFrom, 1)));
  let episodeTo = $state<number>(readEvalInt(PREF_KEYS.evalEpisodeTo, 50));

  // Selected legs to compare (flat/graphiti, knowledge only). Default = both; one must stay. The
  // legs the CURRENT run actually used (`runModes`) live in the run controller (table columns).
  let selectedModes = $state<EvalLeg[]>([...EVAL_ALL_LEGS]);

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

  /** Derive the "Rebuild graph" checkbox default from the selected corpus's graph state:
   *  OFF when a graph already exists (reuse it), ON when none exists (you must build one).
   *  The corpus's graph state wins over the persisted last-used value on every corpus change.
   *  The relevant flag differs by track — memory's "Rebuild graph" is `ingestSynthetic`
   *  (re-remember turns); knowledge's is `buildGraph` (re-ingest entity graph). We write
   *  through the same vars + localStorage keys the setters use, so the persisted value tracks. */
  function applyRebuildDefaultForCorpus() {
    const corpus = deps.getSelectedCorpus();
    if (!corpus) return;
    const rebuild = !corpus.has_graph;
    if (deps.getTrack() === 'memory') {
      ingestSynthetic = rebuild;
      writeLocalBoolean(PREF_KEYS.evalIngest, rebuild);
    } else {
      buildGraph = rebuild;
      writeLocalBoolean(PREF_KEYS.evalBuildGraph, rebuild);
    }
  }

  /** Auto-advance the From/To window past the batch just ingested, so a chunked build "just works"
   *  (run, run, run) without re-typing the range. Shifts BOTH ends by the actual episodes ingested
   *  (the `remember_done` setup event's count) to preserve the window width. No-op when this run
   *  didn't ingest (no remember_done) or ingested to the end (`to` = 0 stays open-ended). */
  function advanceEpisodeWindow() {
    let batch = 0;
    const events = deps.getSetupEvents();
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].phase === 'remember_done') {
        batch = events[i].episode_count ?? 0;
        break;
      }
    }
    if (batch <= 0) return;
    episodeFrom = episodeFrom + batch;
    writeLocalString(PREF_KEYS.evalEpisodeFrom, String(episodeFrom));
    if (episodeTo > 0) {
      episodeTo = episodeTo + batch;
      writeLocalString(PREF_KEYS.evalEpisodeTo, String(episodeTo));
    }
  }

  /** Restore the given corpus's last-used answer-prompt profile ('' ⇒ default). Called on every
   *  corpus change (scan / select). In-memory only — no pref write (we're reading, not choosing). */
  function restoreAnswerPrompt(corpusId: string) {
    answerPromptId = readAnswerPromptPref(corpusId);
  }

  /** Reset the chosen answer-prompt to the default (used on track switch, before a rescan). Does
   *  not persist — the per-corpus pref write only happens when the user picks a profile. */
  function clearAnswerPrompt() {
    answerPromptId = '';
  }

  /** Disarm the per-run "Clear graph first" wipe (after an ingest run is accepted). */
  function disarmClearBefore() {
    clearBefore = false;
  }

  return {
    get ingestSynthetic() {
      return ingestSynthetic;
    },
    set ingestSynthetic(v: boolean) {
      ingestSynthetic = v;
      writeLocalBoolean(PREF_KEYS.evalIngest, v);
    },
    get buildGraph() {
      return buildGraph;
    },
    set buildGraph(v: boolean) {
      buildGraph = v;
      writeLocalBoolean(PREF_KEYS.evalBuildGraph, v);
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
      writeLocalString(PREF_KEYS.evalEpisodeFrom, String(episodeFrom));
    },
    get episodeTo() {
      return episodeTo;
    },
    set episodeTo(v: number) {
      episodeTo = Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
      writeLocalString(PREF_KEYS.evalEpisodeTo, String(episodeTo));
    },
    // Whether the selected corpus already has a graph (drives the run-time wipe warning).
    get selectedCorpusHasGraph() {
      return deps.getSelectedCorpus()?.has_graph ?? false;
    },
    // The track's active "Rebuild graph" flag — memory uses `ingestSynthetic`, knowledge `buildGraph`.
    get rebuildChecked() {
      return deps.getTrack() === 'memory' ? ingestSynthetic : buildGraph;
    },
    get judge() {
      return judge;
    },
    set judge(v: boolean) {
      judge = v;
      writeLocalBoolean(PREF_KEYS.evalJudge, v);
    },
    // Memory track — chosen answer-prompt profile id ('' ⇒ default). Sticky per corpus.
    get answerPromptId() {
      return answerPromptId;
    },
    set answerPromptId(v: string) {
      answerPromptId = v;
      writeAnswerPromptPref(deps.getSelectedCorpusId(), v);
    },
    // Memory track — parallel-question cap (1 = serial). Clamped to the server ceiling here
    // too so a hand-typed value never round-trips just to be clamped server-side.
    get questionConcurrency() {
      return questionConcurrency;
    },
    set questionConcurrency(v: number) {
      questionConcurrency = Number.isFinite(v)
        ? Math.min(QUESTION_CONCURRENCY_MAX, Math.max(1, Math.floor(v)))
        : 1;
      writeLocalString(PREF_KEYS.evalQuestionConcurrency, String(questionConcurrency));
    },
    get questionConcurrencyMax() {
      return QUESTION_CONCURRENCY_MAX;
    },
    get selectedModes() {
      return selectedModes;
    },
    isModeSelected,
    toggleMode,
    applyRebuildDefaultForCorpus,
    advanceEpisodeWindow,
    restoreAnswerPrompt,
    clearAnswerPrompt,
    disarmClearBefore
  };
}

export type EvalSetup = ReturnType<typeof createEvalSetup>;
