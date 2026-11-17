/**
 * Retrieval-pipeline-trace dialog controller (memory/trace/retrieval-trace-dialog.svelte).
 *
 * Owns the "open the per-search trace dialog with the answer on its Overview" flow: a run's trace
 * from a trace button, one sub-query's trace from a recall's trajectory. The app hands in where the
 * traces come from (`TraceSource`) and how to tell the person a trace is missing. An eval also hands
 * in the question's ideal answer, which the Overview shows above the answer.
 *
 * Follows getters for `$derived`/`$state` consumers (avoid returning shorthand — stale capture).
 */
import { errorMessage } from '$kit/api/client';
import type { RetrievalTraceRecord, TraceSource } from '$kit/memory/source';
import type { ToastKind } from '$kit/ui/toast.svelte';

export function createRetrievalTraceDialogController(
	source: TraceSource,
	notify: (kind: ToastKind, message: string) => void
) {
	let activeTrace = $state<RetrievalTraceRecord | null>(null);
	// The answer, shown on the trace dialog's Overview tab; the ideal answer above it when one was given.
	let activeTraceAnswer = $state('');
	let activeTraceIdeal = $state<string | undefined>(undefined);
	let traceLoadingRunId = $state<string | null>(null);
	// Per-sub-query loading (agentic recall): the trajectory's per-search Trace buttons share one
	// run_id, so a run-keyed spinner would light them all — key the spinner on the sub-query sid.
	let traceLoadingSid = $state<number | null>(null);

	// Open the run's retrieval pipeline trace for the global (per-leg) Trace button.
	// Agentic recall writes one trace PER concurrent sub-query, so a run can hold several; prefer
	// the trace whose query is the original question, else the lowest-sid search (deterministic —
	// concurrent sub-queries are written in nondeterministic order, so "last" was a coin flip).
	async function openTrace(runId: string, answer = '', question = '', ideal?: string) {
		traceLoadingRunId = runId;
		try {
			const traces = await source.retrievalTrace(runId);
			if (traces.length > 0) {
				const q = question.trim();
				const matched = q ? traces.find((t) => (t.query ?? '').trim() === q) : undefined;
				const lowestSid = [...traces].sort((a, b) => (a.sid ?? 0) - (b.sid ?? 0))[0];
				activeTrace = matched ?? lowestSid;
				activeTraceAnswer = answer;
				activeTraceIdeal = ideal;
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
	async function openTraceForSubQuery(runId: string, sid: number, answer = '', ideal?: string) {
		traceLoadingSid = sid;
		try {
			const traces = await source.retrievalTrace(runId);
			const matched = traces.find((t) => t.sid === sid);
			if (matched) {
				activeTrace = matched;
				activeTraceAnswer = answer;
				activeTraceIdeal = ideal;
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
		get activeTraceIdeal() {
			return activeTraceIdeal;
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
