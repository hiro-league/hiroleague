/**
 * L3 prototype (Phase 5e) — controller for the Eval Batch section under the Ask tab.
 *
 * Responsibilities:
 *  - Setup form state (ingest_synthetic / build_graph checkboxes + Run button)
 *  - Triggering ``POST /knowledge/eval/run`` (returns run_id; eval runs in background)
 *  - Subscribing to the ``/knowledge/events`` SSE stream for the matching run_id
 *  - Buffering per-question rows as they arrive (UI table re-renders reactively)
 *  - Surface the final PROCEED/PIVOT gate when the ``completed`` event lands
 *
 * SSE subscription stays open for the lifetime of the controller — events for runs
 * we don't care about (different run_id) are dropped at the controller layer. That
 * lets one connection survive across multiple sequential eval runs.
 */
import {
  connectKnowledgeEvalEvents,
  type EvalCompletedPayload,
  type EvalFailedPayload,
  type EvalQuestionPayload,
  type EvalSetupProgressPayload,
  type EvalStartedPayload
} from '$lib/features/knowledge/shared/knowledge-events';
import { runKnowledgeEval } from '$lib/api/knowledge';
import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readLocalBoolean,
  readSessionString,
  removeSessionString,
  writeLocalBoolean,
  writeSessionString
} from '$lib/preferences/storage';

export type EvalStatus =
  | 'idle'         // nothing has run yet (or the last run was cleared)
  | 'starting'    // POST sent, waiting for the started event
  | 'running'     // started event received, question events streaming
  | 'completed'   // completed event received
  | 'failed';     // failed event received OR transport error

/** What we render per question — populated as ``question_completed`` events arrive. */
export type EvalRow = {
  index: number;
  total: number;
  id: string;
  category: string;
  question: string;
  requires_graph: boolean;
  flatMark: string;
  flatElapsedMs: number;
  flatRunId: string | null;
  graphMark: string;
  graphElapsedMs: number;
  graphRunId: string | null;
  delta: string;
};

/** Persisted snapshot of the last terminal (completed/failed) eval run.
 *  Mid-run state is intentionally NOT persisted — if the user navigates away
 *  during a run, the SSE closes and partial state would be misleading (the
 *  backend keeps running in a fire-and-forget task; coming back shows the
 *  PREVIOUS terminal run, not the in-flight one). When the in-flight run
 *  later completes its event is missed → user re-asks if they want it. */
type EvalRunSnapshot = {
  runId: string | null;
  totalQuestions: number;
  status: 'completed' | 'failed';
  rows: EvalRow[];
  summary: EvalCompletedPayload | null;
  failureMessage: string | null;
};

function readPersistedEvalRun(): EvalRunSnapshot | null {
  const raw = readSessionString(PREF_KEYS.knowledgeAskEvalRun);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as EvalRunSnapshot;
    // Defensive shape check — corrupt payloads (e.g. schema drift across
    // versions) drop rather than crash the panel on first paint.
    if (
      parsed
      && typeof parsed === 'object'
      && Array.isArray(parsed.rows)
      && (parsed.status === 'completed' || parsed.status === 'failed')
    ) {
      return parsed;
    }
  } catch {
    // Fall through to clear.
  }
  removeSessionString(PREF_KEYS.knowledgeAskEvalRun);
  return null;
}

function writePersistedEvalRun(snapshot: EvalRunSnapshot) {
  writeSessionString(PREF_KEYS.knowledgeAskEvalRun, JSON.stringify(snapshot));
}

function clearPersistedEvalRun() {
  removeSessionString(PREF_KEYS.knowledgeAskEvalRun);
}

export function createKnowledgeEvalModel(deps: {
  setError: (message: string | null) => void;
}) {
  // Setup-form state — defaults off, but the user's last choice persists across
  // reloads via localStorage (mirrors the ingest tab's buildGraphAfter pattern).
  let ingestSynthetic = $state<boolean>(
    readLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, false)
  );
  let buildGraph = $state<boolean>(
    readLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, false)
  );

  // Hydrate the run snapshot from session storage so leaving + returning to the
  // Ask tab shows the last completed table (mirrors knowledgeAskResult on the
  // single-mode side). Only terminal states are ever written, so the restored
  // status is always 'completed' or 'failed' — no half-finished runs.
  const persisted = readPersistedEvalRun();
  let status = $state<EvalStatus>(persisted?.status ?? 'idle');
  let runId = $state<string | null>(persisted?.runId ?? null);
  let totalQuestions = $state(persisted?.totalQuestions ?? 0);
  let rows = $state<EvalRow[]>(persisted?.rows ?? []);
  let summary = $state<EvalCompletedPayload | null>(persisted?.summary ?? null);
  let failureMessage = $state<string | null>(persisted?.failureMessage ?? null);
  let setupPhase = $state<EvalSetupProgressPayload | null>(null);

  // ONE EventSource for the controller's lifetime. We filter by run_id below
  // — events from other runs (e.g. a parallel CLI invocation) are ignored.
  let teardownEvents: (() => void) | null = null;

  function ensureSubscribed() {
    if (teardownEvents) return;
    teardownEvents = connectKnowledgeEvalEvents({
      onStarted: handleStarted,
      onSetupProgress: handleSetupProgress,
      onQuestion: handleQuestion,
      onCompleted: handleCompleted,
      onFailed: handleFailed
    });
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
    setupPhase = null;  // we're past setup once started fires
  }

  function handleSetupProgress(p: EvalSetupProgressPayload) {
    // Setup events fire BEFORE started, while runId is still set (we set it
    // from the POST response). No run_id on this event by current design;
    // accept any setup event while we're in 'starting' state.
    if (status === 'starting') {
      setupPhase = p;
    }
  }

  function handleQuestion(p: EvalQuestionPayload) {
    // We don't have a per-event run_id on question events today; gate by status.
    if (status !== 'running') return;
    const row: EvalRow = {
      index: p.index,
      total: p.total,
      id: p.id,
      category: p.category,
      question: p.question,
      requires_graph: p.requires_graph,
      flatMark: p.flat.mark,
      flatElapsedMs: p.flat.elapsed_ms,
      flatRunId: p.flat.run_id,
      graphMark: p.graph.mark,
      graphElapsedMs: p.graph.elapsed_ms,
      graphRunId: p.graph.run_id,
      delta: p.delta
    };
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
    persistCurrentRun();
  }

  function handleFailed(p: EvalFailedPayload) {
    if (!isOurRun(p.run_id)) return;
    failureMessage = p.error;
    status = 'failed';
    persistCurrentRun();
  }

  /** Snapshot terminal state to sessionStorage. Called only from completed/
   *  failed handlers — see EvalRunSnapshot for why mid-run isn't persisted. */
  function persistCurrentRun() {
    if (status !== 'completed' && status !== 'failed') return;
    writePersistedEvalRun({
      runId,
      totalQuestions,
      status,
      rows,
      summary,
      failureMessage
    });
  }

  async function start() {
    if (status === 'starting' || status === 'running') return;
    // Fresh slate every run — last run's table doesn't bleed into this one.
    rows = [];
    summary = null;
    failureMessage = null;
    setupPhase = null;
    runId = null;
    totalQuestions = 0;
    status = 'starting';
    deps.setError(null);
    ensureSubscribed();

    try {
      const res = await runKnowledgeEval({
        ingest_synthetic: ingestSynthetic,
        build_graph: buildGraph
      });
      runId = res.data.run_id;
      // If a 'started' event already arrived before runId got set above, the
      // controller would have ignored it (isOurRun=false). In practice the
      // POST response returns before the started event, but if a future change
      // reverses that ordering we'd need to buffer events. Documented for now.
    } catch (err) {
      status = 'failed';
      failureMessage = err instanceof Error ? err.message : 'Failed to start eval run.';
      deps.setError(failureMessage);
    }
  }

  function clear() {
    if (status === 'starting' || status === 'running') return;
    rows = [];
    summary = null;
    failureMessage = null;
    setupPhase = null;
    runId = null;
    totalQuestions = 0;
    status = 'idle';
    clearPersistedEvalRun();
  }

  return {
    get ingestSynthetic() { return ingestSynthetic; },
    set ingestSynthetic(v: boolean) {
      ingestSynthetic = v;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalIngest, v);
    },
    get buildGraph() { return buildGraph; },
    set buildGraph(v: boolean) {
      buildGraph = v;
      writeLocalBoolean(PREF_KEYS.knowledgeAskEvalBuildGraph, v);
    },
    get status() { return status; },
    get runId() { return runId; },
    get totalQuestions() { return totalQuestions; },
    get rows() { return rows; },
    get summary() { return summary; },
    get failureMessage() { return failureMessage; },
    get setupPhase() { return setupPhase; },
    start,
    clear,
    teardown
  };
}

export type KnowledgeEvalModel = ReturnType<typeof createKnowledgeEvalModel>;
