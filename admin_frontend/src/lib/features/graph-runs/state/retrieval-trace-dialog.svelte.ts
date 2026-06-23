/**
 * Shared retrieval-pipeline-trace dialog controller.
 *
 * Owns the "open the per-search trace dialog with the question's ideal + model answer in the
 * header" flow that both the Eval panel (answer rows / trajectory sub-queries) and the Graph-Runs
 * → eval-detail bridge use. Extracted out of `eval-traces` so the Graph-Runs page can drive the
 * exact same dialog without depending on the whole `EvalModel` (DRY — one copy of the
 * sid/query-matching logic, per the common-utility rule).
 *
 * Follows getters for `$derived`/`$state` consumers (avoid returning shorthand — stale capture).
 */
import {
  getGraphRunRetrievalTrace,
  type RetrievalTraceRecord
} from '$lib/api/graph-runs';
import type { ToastKind } from '$lib/ui/toast-types';

export function createRetrievalTraceDialogController(
  notify: (kind: ToastKind, message: string) => void
) {
  let activeTrace = $state<RetrievalTraceRecord | null>(null);
  // Ideal + model answer for the trace's question, surfaced in the dialog header.
  let activeTraceIdeal = $state('');
  let activeTraceAnswer = $state('');
  let traceLoadingRunId = $state<string | null>(null);
  // Per-sub-query loading (agentic recall): the trajectory's per-search Trace buttons share one
  // run_id, so a run-keyed spinner would light them all — key the spinner on the sub-query sid.
  let traceLoadingSid = $state<number | null>(null);

  // Open the run's retrieval pipeline trace for the global (per-leg) Trace button.
  // Agentic recall writes one trace PER concurrent sub-query, so a run can hold several; prefer
  // the trace whose query is the original question, else the lowest-sid search (deterministic —
  // concurrent sub-queries are written in nondeterministic order, so "last" was a coin flip).
  async function openTrace(runId: string, ideal = '', answer = '', question = '') {
    traceLoadingRunId = runId;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        const q = question.trim();
        const matched = q ? traces.find((t) => (t.query ?? '').trim() === q) : undefined;
        const lowestSid = [...traces].sort((a, b) => (a.sid ?? 0) - (b.sid ?? 0))[0];
        activeTrace = matched ?? lowestSid;
        activeTraceIdeal = ideal;
        activeTraceAnswer = answer;
      } else {
        notify(
          'error',
          'No retrieval trace recorded for this run (graph tracing may have been off).'
        );
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load retrieval trace.');
    } finally {
      traceLoadingRunId = null;
    }
  }

  // Open the pipeline trace for ONE agentic sub-query (the trajectory tab's per-search button).
  // Matches on the stamped `sid` — the reliable key now that the backend tags each sub-query's
  // trace (concurrent writes mean list order ≠ sid order, so we can't index positionally).
  async function openTraceForSubQuery(runId: string, sid: number, ideal = '', answer = '') {
    traceLoadingSid = sid;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      const matched = traces.find((t) => t.sid === sid);
      if (matched) {
        activeTrace = matched;
        activeTraceIdeal = ideal;
        activeTraceAnswer = answer;
      } else {
        notify(
          'error',
          `No pipeline trace recorded for search S${sid} (graph tracing may have been off).`
        );
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load retrieval trace.');
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
    get activeTraceIdeal() {
      return activeTraceIdeal;
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
