/**
 * Run-lifecycle + SSE controller for the Eval panel. Owns the live run state machine: the one
 * EventSource subscription, the per-event handlers, server-state hydration, and the run-state
 * mutators that `createEvalModel`'s `start` / `clear` / `loadResults` drive.
 *
 * It deliberately does NOT own the setup form, corpus picker, or saved-results — those stay in the
 * data model, which injects a narrow `EvalRunCtx` so this controller can read the active track,
 * adopt a server-reported track mid-run, and notify the model on terminal events / after hydrate.
 * Source of truth is server-side (`GET /knowledge/eval/state`); there is no sessionStorage.
 */
import {
  connectKnowledgeEvalEvents,
  type EvalCancelledPayload,
  type EvalCompletedPayload,
  type EvalFailedPayload,
  type EvalQuestionPayload,
  type EvalRunStateData,
  type EvalSetupProgressPayload,
  type EvalStartedPayload
} from '$lib/features/knowledge/shared/knowledge-events';
import { cancelKnowledgeEval, getKnowledgeEvalState } from '$lib/api/knowledge';
import { rowFromPayload, type EvalRow, type EvalStatus, type EvalTrack } from '$lib/features/eval/shared/eval-row';

/** Narrow seam back to the data model — kept small on purpose (see the module doc). */
export type EvalRunCtx = {
  setError: (message: string | null) => void;
  /** The user's active track (the data model owns it; this controller only reads it). */
  getTrack: () => EvalTrack;
  /** Adopt the server's run track while a run is live (mid-run navigation / cross-origin). */
  setTrackFromServer: (track: EvalTrack) => void;
  /** A terminal event landed — the model reconciles saved results (+ advances the episode window
   *  on `completed`). Gating by track lives in the model. */
  onTerminal: (kind: 'completed' | 'failed' | 'cancelled') => void;
  /** Server state was replayed — the model reconciles the on-disk snapshot when appropriate. */
  afterHydrate: () => void;
};

export function createEvalRunController(ctx: EvalRunCtx, opts: { initialModes: string[] }) {
  // Run state — hydrated from the server on mount, then kept live by the SSE handlers. No
  // sessionStorage: the server registry is the single source of truth so navigation +
  // cross-origin stay consistent.
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
  // The legs the CURRENT run actually used (started/state event) — drives table columns.
  let runModes = $state<string[]>([...opts.initialModes]);

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
      // BUGFIX context: applyServerState replays only the server's LAST RUN; the model reconciles
      // the full on-disk snapshot afterwards (guarded for live runs + the right track/corpus).
      ctx.afterHydrate();
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
      ctx.setTrackFromServer(state.track);
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
    ctx.onTerminal('completed');
  }

  function handleFailed(p: EvalFailedPayload) {
    if (!isOurRun(p.run_id)) return;
    failureMessage = p.error;
    status = 'failed';
    cancelling = false;
    ctx.onTerminal('failed');
  }

  function handleCancelled(p: EvalCancelledPayload) {
    if (!isOurRun(p.run_id)) return;
    status = 'cancelled';
    cancelling = false;
    ctx.onTerminal('cancelled');
  }

  /** Fresh-slate the run state for a new run and lock the table columns to `modes` (memory =
   *  ['recall']; knowledge = the picked legs), then ensure the SSE is connected. The model does
   *  the POST and follows up with `setRunId` / `markFailed`. */
  function beginStarting(modes: string[]) {
    rows = [];
    summary = null;
    failureMessage = null;
    setupPhase = null;
    setupEvents = [];
    cancelling = false;
    runId = null;
    totalQuestions = 0;
    status = 'starting';
    runModes = modes;
    ensureSubscribed();
  }

  function setRunId(id: string) {
    runId = id;
  }

  function markFailed(message: string | null) {
    status = 'failed';
    failureMessage = message;
  }

  /** Replay a saved on-disk snapshot into the table/summary (memory track, when idle). Caller
   *  maps payloads to rows; we sort + derive the leg columns and the completed/idle status. */
  function applySnapshot(snapshotRows: EvalRow[], snapshotSummary: EvalCompletedPayload | null) {
    rows = [...snapshotRows].sort((a, b) => a.index - b.index);
    summary = snapshotSummary;
    // Lock the table/fold leg columns to the snapshot's legs (memory = ['recall']). Without this,
    // runModes stays at the default flat/graphiti and the memory rows' `recall` leg matches no
    // column → expanded rows render empty.
    runModes = snapshotSummary?.modes?.length ? snapshotSummary.modes : ['recall'];
    failureMessage = null;
    // A non-empty snapshot reads as a completed (saved) run; empty falls back to idle.
    status = rows.length > 0 ? 'completed' : 'idle';
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
      ctx.setError(err instanceof Error ? err.message : 'Failed to cancel eval run.');
    }
  }

  return {
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
    get runModes() {
      return runModes;
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
    ensureSubscribed,
    hydrateFromServer,
    resetRunState,
    beginStarting,
    setRunId,
    markFailed,
    applySnapshot,
    cancel,
    teardown
  };
}

export type EvalRunController = ReturnType<typeof createEvalRunController>;
