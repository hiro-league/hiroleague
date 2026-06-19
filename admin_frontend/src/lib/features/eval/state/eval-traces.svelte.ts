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
import { exportEvalResultsLocomo } from '$lib/api/knowledge';
import { seedGraphEpisodeFocus } from '$lib/features/knowledge/graph/knowledge-graph-prefs';
import { formatEvalRowForAI } from '$lib/features/eval/shared/eval-clipboard';
import type { EvalRow } from '$lib/features/eval/shared/eval-row';
import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';

/** Narrow read-seam back to the panel: the model + the (prefs-derived) compact engine line that
 *  the per-row "Copy for AI" brief embeds. Kept as accessors so they stay reactive. */
export type EvalTracesCtx = {
  eval_: EvalModel;
  /** Compact engine line for the copy brief (derived from prefs in the panel). */
  getAiEngine: () => string;
};

export function createEvalTraces(ctx: EvalTracesCtx) {
  const { eval_ } = ctx;

  // --- Retrieval pipeline trace (graph legs only) -------------------------------------------
  let activeTrace = $state<RetrievalTraceRecord | null>(null);
  // Ideal + model answer for the trace's question, surfaced in the dialog header.
  let activeTraceIdeal = $state('');
  let activeTraceAnswer = $state('');
  let traceLoadingRunId = $state<string | null>(null);
  let traceError = $state<string | null>(null);

  async function openTrace(runId: string, ideal = '', answer = '') {
    traceError = null;
    traceLoadingRunId = runId;
    try {
      const res = await getGraphRunRetrievalTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        // A recall is one fact search → one trace; take the latest if a run held several.
        activeTrace = traces[traces.length - 1];
        activeTraceIdeal = ideal;
        activeTraceAnswer = answer;
      } else {
        traceError = 'No retrieval trace recorded for this run (graph tracing may have been off).';
      }
    } catch (err) {
      traceError = err instanceof Error ? err.message : 'Failed to load retrieval trace.';
    } finally {
      traceLoadingRunId = null;
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
  let ingestTraceError = $state<string | null>(null);

  async function openIngestTrace(runId: string) {
    ingestTraceError = null;
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length > 0) {
        ingestTraces = traces;
        ingestTraceIndex = 0;
        activeIngestTrace = traces[0];
      } else {
        ingestTraceError = 'No ingest trace recorded for this run (graph tracing may have been off).';
      }
    } catch (err) {
      ingestTraceError = err instanceof Error ? err.message : 'Failed to load ingest trace.';
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
    ingestTraceError = null;
    ingestTraceLoading = true;
    try {
      const res = await getGraphRunIngestTrace(info.runId);
      const traces = res.ok && res.data ? (res.data.traces ?? []) : [];
      if (traces.length === 0) {
        ingestTraceError = 'No ingest trace recorded for this episode (graph tracing may have been off).';
        return;
      }
      let idx = traces.findIndex((t) => t.chunk_id === info.id);
      if (idx < 0 && info.stepIndex !== '')
        idx = traces.findIndex((t) => t.step_index === info.stepIndex);
      ingestTraces = traces;
      ingestTraceIndex = idx >= 0 ? idx : 0;
      activeIngestTrace = traces[ingestTraceIndex];
    } catch (err) {
      ingestTraceError = err instanceof Error ? err.message : 'Failed to load ingest trace.';
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
  let copyError = $state<string | null>(null);

  async function copyRowForAI(r: EvalRow) {
    copyError = null;
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
      copyError = err instanceof Error ? err.message : 'Could not copy to clipboard.';
    }
  }

  // --- LoCoMo export (memory track) ---------------------------------------------------------
  let exportingLocomo = $state(false);
  let locomoExportError = $state<string | null>(null);
  let locomoExportNotice = $state<string | null>(null);

  async function exportLocomoResults() {
    const corpus = eval_.selectedCorpus;
    if (!corpus) return;
    exportingLocomo = true;
    locomoExportError = null;
    locomoExportNotice = null;
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
      locomoExportNotice = `${res.data.exported_count}/${res.data.total_count} LoCoMo rows exported${
        res.data.partial ? ' (partial)' : ''
      }.`;
      setTimeout(() => {
        locomoExportNotice = null;
      }, 3500);
    } catch (err) {
      locomoExportError = err instanceof Error ? err.message : 'Could not export LoCoMo results.';
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
    get traceError() {
      return traceError;
    },
    openTrace,
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
    get ingestTraceError() {
      return ingestTraceError;
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
    get copyError() {
      return copyError;
    },
    copyRowForAI,
    // LoCoMo export surface.
    get exportingLocomo() {
      return exportingLocomo;
    },
    get locomoExportError() {
      return locomoExportError;
    },
    get locomoExportNotice() {
      return locomoExportNotice;
    },
    exportLocomoResults
  };
}

export type EvalTraces = ReturnType<typeof createEvalTraces>;
