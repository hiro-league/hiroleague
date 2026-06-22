/**
 * Trace / copy / export orchestration for the Eval panel.
 *
 * The retrieval-trace + ingest-trace dialogs are opened from THREE places — answer rows
 * (retrieval trace, per-row "Copy for AI"), the Execute-tab cost strip (run-level ingest
 * pipeline), and the Corpus tab (per-episode ingest pipeline / open-in-graph). Because no single
 * pane owns that state, it lives here; the panel renders the dialogs + transient banners against
 * this controller and every pane calls these methods. Keeps the view components thin (the dialog
 * fetch/loading/error bookkeeping is async orchestration, not markup).
 */
import { goto } from '$app/navigation';
import {
  getGraphRunIngestTrace,
  getGraphRunRetrievalTrace,
  type IngestTraceRecord,
  type RetrievalTraceRecord
} from '$lib/api/graph-runs';
import { exportEvalResultsLocomo } from '$lib/api/eval';
import { seedGraphEpisodeFocus } from '$lib/features/knowledge/graph/knowledge-graph-prefs';
import { formatEvalRowForAI } from '$lib/features/eval/shared/eval-clipboard';
import type { EvalRow } from '$lib/features/eval/shared/eval-row';
import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
import type { ToastKind } from '$lib/ui/toast-types';

/** Narrow read-seam back to the panel: the model + the (prefs-derived) compact engine line that
 *  the per-row "Copy for AI" brief embeds. Kept as accessors so they stay reactive. */
export type EvalTracesCtx = {
  eval_: EvalModel;
  /** Compact engine line for the copy brief (derived from prefs in the panel). */
  getAiEngine: () => string;
  /** Canonical toast notifier from the host page (transient trace/copy/export feedback). */
  getNotify: () => (kind: ToastKind, message: string) => void;
};

export function createEvalTraces(ctx: EvalTracesCtx) {
  const { eval_ } = ctx;
  const notify = (kind: ToastKind, message: string) => ctx.getNotify()(kind, message);

  // --- Retrieval pipeline trace (graph legs only) -------------------------------------------
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

  // --- Ingest (graph-build) pipeline trace --------------------------------------------------
  let activeIngestTrace = $state<IngestTraceRecord | null>(null);
  // Full per-episode trace list for the open run + current index, so the dialog's prev/next
  // arrows can step through every episode of the remember run.
  let ingestTraces = $state<IngestTraceRecord[]>([]);
  let ingestTraceIndex = $state(0);
  let ingestTraceLoading = $state(false);

  async function openIngestTrace(runId: string) {
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        ingestTraces = traces;
        ingestTraceIndex = 0;
        activeIngestTrace = traces[0];
      } else {
        notify('error', 'No ingest trace recorded for this run (graph tracing may have been off).');
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load ingest trace.');
    } finally {
      ingestTraceLoading = false;
    }
  }

  /** Open the ingest-pipeline dialog for ONE corpus episode (Corpus tab "pipeline" button). Loads
   *  that episode's remember run, then positions the dialog on the matching episode (by chunk_id,
   *  falling back to step_index) so it opens straight to that turn's pipeline. */
  async function openIngestTraceForEpisode(info: {
    id: string;
    runId: string;
    stepIndex: number | '';
  }) {
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(info.runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length === 0) {
        notify(
          'error',
          'No ingest trace recorded for this episode (graph tracing may have been off).'
        );
        return;
      }
      let idx = traces.findIndex((t) => t.chunk_id === info.id);
      if (idx < 0 && info.stepIndex !== '')
        idx = traces.findIndex((t) => t.step_index === info.stepIndex);
      ingestTraces = traces;
      ingestTraceIndex = idx >= 0 ? idx : 0;
      activeIngestTrace = traces[ingestTraceIndex];
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load ingest trace.');
    } finally {
      ingestTraceLoading = false;
    }
  }

  /** Step the open ingest-trace dialog to the prev/next episode of the run (arrow-nav). */
  function stepIngestTrace(delta: number) {
    const j = ingestTraceIndex + delta;
    if (j >= 0 && j < ingestTraces.length) {
      ingestTraceIndex = j;
      activeIngestTrace = ingestTraces[j];
    }
  }

  function closeIngestTrace() {
    activeIngestTrace = null;
    ingestTraces = [];
    ingestTraceIndex = 0;
  }

  /** Open the Knowledge Graph view (Memories page, Graph tab) focused on ONE corpus episode: seed
   *  the active group + that episode's chunk_id into the graph's session state, then navigate.
   *  No-op if the corpus's eval group isn't known yet (extraction not loaded / untraced corpus). */
  function openGraphForEpisode(info: { id: string }) {
    const group = eval_.corpusExtractionGroup;
    if (!group) return;
    seedGraphEpisodeFocus(group, info.id);
    void goto('/memories?tab=graph');
  }

  // --- Per-row "Copy for AI" ----------------------------------------------------------------
  let copiedRow = $state<number | null>(null);

  async function copyRowForAI(r: EvalRow) {
    try {
      const text = formatEvalRowForAI({
        row: r,
        legColumns: eval_.runModes,
        track: eval_.track,
        engine: ctx.getAiEngine(),
        corpus: eval_.selectedCorpus?.id ?? '',
        logDir: eval_.logDir
      });
      await navigator.clipboard.writeText(text);
      copiedRow = r.index;
      setTimeout(() => {
        if (copiedRow === r.index) copiedRow = null;
      }, 1500);
    } catch (err) {
      notify('error', `Copy for AI failed: ${err instanceof Error ? err.message : 'Could not copy to clipboard.'}`);
    }
  }

  // --- LoCoMo export (memory track) ---------------------------------------------------------
  let exportingLocomo = $state(false);

  async function exportLocomoResults() {
    const corpus = eval_.selectedCorpus;
    if (!corpus) return;
    exportingLocomo = true;
    try {
      const res = await exportEvalResultsLocomo(corpus.id, corpus.questions_path);
      const blob = new Blob([res.data.content], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      notify(
        'success',
        `${res.data.exported_count}/${res.data.total_count} LoCoMo rows exported${
          res.data.partial ? ' (partial)' : ''
        }.`
      );
    } catch (err) {
      notify(
        'error',
        `LoCoMo export failed: ${err instanceof Error ? err.message : 'Could not export LoCoMo results.'}`
      );
    } finally {
      exportingLocomo = false;
    }
  }

  return {
    // Retrieval trace surface.
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
    closeTrace,
    // Ingest trace surface.
    get activeIngestTrace() {
      return activeIngestTrace;
    },
    get ingestTraces() {
      return ingestTraces;
    },
    get ingestTraceIndex() {
      return ingestTraceIndex;
    },
    get ingestTraceLoading() {
      return ingestTraceLoading;
    },
    openIngestTrace,
    openIngestTraceForEpisode,
    stepIngestTrace,
    closeIngestTrace,
    openGraphForEpisode,
    // Copy-for-AI surface.
    get copiedRow() {
      return copiedRow;
    },
    copyRowForAI,
    // LoCoMo export surface.
    get exportingLocomo() {
      return exportingLocomo;
    },
    exportLocomoResults
  };
}

export type EvalTraces = ReturnType<typeof createEvalTraces>;
