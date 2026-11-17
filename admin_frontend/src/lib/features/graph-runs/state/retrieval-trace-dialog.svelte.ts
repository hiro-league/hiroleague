/**
 * Retrieval-pipeline-trace dialog controller for the chat recall detail dialog.
 *
 * Owns the "open the per-search trace dialog with the recall's draft answer on its Overview" flow:
 * the run's trace from the recall's trace button, one sub-query's trace from the Trajectory tab.
 *
 * Follows getters for `$derived`/`$state` consumers (avoid returning shorthand — stale capture).
 */
import { errorMessage } from '$kit/api/client';
import {
  getGraphRunRetrievalTrace,
  type RetrievalTraceRecord
} from '$lib/api/graph-runs';
import type { ToastKind } from '$kit/ui/toast.svelte';

export function createRetrievalTraceDialogController(
  notify: (kind: ToastKind, message: string) => void
) {
  let activeTrace = $state<RetrievalTraceRecord | null>(null);
  // The recall's draft answer, shown on the trace dialog's Overview tab.
  let activeTraceAnswer = $state('');
  let traceLoadingRunId = $state<string | null>(null);
  // Per-sub-query loading (agentic recall): the trajectory's per-search Trace buttons share one
  // run_id, so a run-keyed spinner would light them all — key the spinner on the sub-query sid.
  let traceLoadingSid = $state<number | null>(null);

  // Open the run's retrieval pipeline trace for the global (per-leg) Trace button.
  // Agentic recall writes one trace PER concurrent sub-query, so a run can hold several; prefer
  // the trace whose query is the original question, else the lowest-sid search (deterministic —
  // concurrent sub-queries are written in nondeterministic order, so "last" was a coin flip).
  async function openTrace(runId: string, answer = '', question = '') {
    traceLoadingRunId = runId;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.traces ?? [];
      if (traces.length > 0) {
        const q = question.trim();
        const matched = q ? traces.find((t) => (t.query ?? '').trim() === q) : undefined;
        const lowestSid = [...traces].sort((a, b) => (a.sid ?? 0) - (b.sid ?? 0))[0];
        activeTrace = matched ?? lowestSid;
        activeTraceAnswer = answer;
      } else {
        notify(
          'error',
          'No retrieval trace recorded for this run (graph tracing may have been off).'
        );
      }
    } catch (err) {
      notify('error', errorMessage(err));
    } finally {
      traceLoadingRunId = null;
    }
  }

  // Open the pipeline trace for ONE agentic sub-query (the trajectory tab's per-search button).
  // Matches on the stamped `sid` — the reliable key now that the backend tags each sub-query's
  // trace (concurrent writes mean list order ≠ sid order, so we can't index positionally).
  async function openTraceForSubQuery(runId: string, sid: number, answer = '') {
    traceLoadingSid = sid;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.traces ?? [];
      const matched = traces.find((t) => t.sid === sid);
      if (matched) {
        activeTrace = matched;
        activeTraceAnswer = answer;
      } else {
        notify(
          'error',
          `No pipeline trace recorded for search S${sid} (graph tracing may have been off).`
        );
      }
    } catch (err) {
      notify('error', errorMessage(err));
    } finally {
      traceLoadingSid = null;
    }
  }

  function closeTrace() {
    activeTrace = null;
  }

  return {
    get activeTrace() {
      return activeTrace;
    },
    get activeTraceAnswer() {
      return activeTraceAnswer;
    },
    get traceLoadingRunId() {
      return traceLoadingRunId;
    },
    get traceLoadingSid() {
      return traceLoadingSid;
    },
    openTrace,
    openTraceForSubQuery,
    closeTrace
  };
}

export type RetrievalTraceDialogController = ReturnType<
  typeof createRetrievalTraceDialogController
>;
