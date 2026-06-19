/**
 * Retrieval (Graphiti fact-search) + ingest (`add_episode`) trace sub-model for the
 * Graph Runs inspector. Owns the per-run trace caches, the open-dialog target step for
 * each lane, and the derived markers / arrow-nav state the detail panel + dialogs read.
 *
 * Split out of `graph-runs-controller` to keep that controller focused on the ledger /
 * inspector lifecycle. The model is reactive against the host's active pane (passed as a
 * getter) so its `*ForActive` derivations recompute when the user switches open runs.
 *
 * Follows getters for `$derived` consumers (avoid returning shorthand `$derived` from a
 * factory — that captures a stale value).
 */
import {
  getGraphRunIngestTrace,
  getGraphRunRetrievalTrace,
  type GraphLedgerRow,
  type IngestTraceRecord,
  type RetrievalTraceRecord
} from '$lib/api/graph-runs';
import { RUNS_TAB, type ActivePane } from '../graph-runs-pure';

function rowStepIndex(row: GraphLedgerRow): number {
  return typeof row.step_index === 'number' ? row.step_index : Number(row.step_index);
}

export function createGraphRunTraceModel(opts: { getActivePane: () => ActivePane }) {
  const { getActivePane } = opts;

  /** Per-stage Graphiti fact-search traces per run (only present when tracing was enabled). */
  let retrievalTraceByRun = $state<Record<string, RetrievalTraceRecord[]>>({});
  /** Open retrieval-trace dialog target — the step_index (graph_expand / memory_recall) shown. */
  let retrievalTraceStep = $state<number | null>(null);
  /** Per-stage Graphiti add_episode traces per run (only present when ingest tracing was enabled). */
  let ingestTraceByRun = $state<Record<string, IngestTraceRecord[]>>({});
  /** Open ingest-trace dialog target — the step_index (the episode row) shown. */
  let ingestTraceStep = $state<number | null>(null);

  /** Retrieval traces for the active run, indexed by the `step_index` they were recorded under. */
  const retrievalTraceByStep = $derived.by((): Map<number, RetrievalTraceRecord> => {
    const m = new Map<number, RetrievalTraceRecord>();
    const pane = getActivePane();
    if (pane === RUNS_TAB) return m;
    for (const t of retrievalTraceByRun[pane] ?? []) {
      const step = typeof t.step_index === 'number' ? t.step_index : Number(t.step_index);
      if (Number.isFinite(step)) m.set(step, t);
    }
    return m;
  });

  /** Step indexes (of the active run) that have a retrieval trace — drives the row marker. */
  const retrievalTraceStepIds = $derived.by(
    (): Set<number> => new Set(retrievalTraceByStep.keys())
  );

  const activeRetrievalTrace = $derived.by((): RetrievalTraceRecord | null => {
    if (retrievalTraceStep === null) return null;
    return retrievalTraceByStep.get(retrievalTraceStep) ?? null;
  });

  /** Ingest traces for the active run, indexed by the episode `step_index`. */
  const ingestTraceByStep = $derived.by((): Map<number, IngestTraceRecord> => {
    const m = new Map<number, IngestTraceRecord>();
    const pane = getActivePane();
    if (pane === RUNS_TAB) return m;
    for (const t of ingestTraceByRun[pane] ?? []) {
      const step = typeof t.step_index === 'number' ? t.step_index : Number(t.step_index);
      if (Number.isFinite(step)) m.set(step, t);
    }
    return m;
  });

  /** Episode step indexes (of the active run) that have an ingest trace — drives the row marker. */
  const ingestTraceStepIds = $derived.by((): Set<number> => new Set(ingestTraceByStep.keys()));

  const activeIngestTrace = $derived.by((): IngestTraceRecord | null => {
    if (ingestTraceStep === null) return null;
    return ingestTraceByStep.get(ingestTraceStep) ?? null;
  });

  /** Episode steps with an ingest trace, ascending — the order the dialog's arrow-nav walks. */
  const ingestTraceStepsSorted = $derived.by((): number[] =>
    [...ingestTraceByStep.keys()].sort((a, b) => a - b)
  );
  const ingestTraceHasPrev = $derived.by(
    (): boolean => ingestTraceStep !== null && ingestTraceStepsSorted.indexOf(ingestTraceStep) > 0
  );
  const ingestTraceHasNext = $derived.by((): boolean => {
    if (ingestTraceStep === null) return false;
    const i = ingestTraceStepsSorted.indexOf(ingestTraceStep);
    return i >= 0 && i < ingestTraceStepsSorted.length - 1;
  });
  // 1-based position of the open trace in the run's episode list + total — the dialog's "N/total"
  // label. The per-trace episode_index/total is 1/1 for these per-turn remember ingests, so the
  // real run position is this index, not that field.
  const ingestTraceNavIndex = $derived.by((): number =>
    ingestTraceStep === null ? 0 : ingestTraceStepsSorted.indexOf(ingestTraceStep) + 1
  );
  const ingestTraceNavTotal = $derived.by((): number => ingestTraceStepsSorted.length);

  async function resolveRetrievalTrace(runId: string) {
    const res = await getGraphRunRetrievalTrace(runId);
    retrievalTraceByRun[runId] = res.ok && res.data ? (res.data.traces ?? []) : [];
    retrievalTraceByRun = { ...retrievalTraceByRun };
  }

  async function resolveIngestTrace(runId: string) {
    const res = await getGraphRunIngestTrace(runId);
    ingestTraceByRun[runId] = res.ok && res.data ? (res.data.traces ?? []) : [];
    ingestTraceByRun = { ...ingestTraceByRun };
  }

  /** Fetch both lanes' traces for a run (fire-and-forget; empty caches on failure). */
  function loadFor(runId: string) {
    void resolveRetrievalTrace(runId);
    void resolveIngestTrace(runId);
  }

  /** Drop a run's cached traces (on close of its inspector tab). */
  function clearFor(runId: string) {
    delete retrievalTraceByRun[runId];
    delete ingestTraceByRun[runId];
    retrievalTraceByRun = { ...retrievalTraceByRun };
    ingestTraceByRun = { ...ingestTraceByRun };
  }

  /** Close any open trace dialog (on pane switch / tab open / tab close). */
  function resetOpen() {
    retrievalTraceStep = null;
    ingestTraceStep = null;
  }

  function openRetrievalTrace(row: GraphLedgerRow) {
    const step = rowStepIndex(row);
    retrievalTraceStep = Number.isFinite(step) ? step : null;
  }

  function closeRetrievalTrace() {
    retrievalTraceStep = null;
  }

  function openIngestTrace(row: GraphLedgerRow) {
    const step = rowStepIndex(row);
    ingestTraceStep = Number.isFinite(step) ? step : null;
  }

  function closeIngestTrace() {
    ingestTraceStep = null;
  }

  /** Move the open ingest-trace dialog to the prev/next episode that has a trace (arrow-nav). */
  function stepIngestTrace(delta: number) {
    if (ingestTraceStep === null) return;
    const steps = ingestTraceStepsSorted;
    const i = steps.indexOf(ingestTraceStep);
    if (i === -1) return;
    const j = i + delta;
    if (j >= 0 && j < steps.length) ingestTraceStep = steps[j];
  }

  return {
    /** Raw open-dialog targets — the Esc handler checks these to know what to close first. */
    get retrievalTraceStep() {
      return retrievalTraceStep;
    },
    get ingestTraceStep() {
      return ingestTraceStep;
    },
    get retrievalTraceStepIds() {
      return retrievalTraceStepIds;
    },
    get activeRetrievalTrace() {
      return activeRetrievalTrace;
    },
    get ingestTraceStepIds() {
      return ingestTraceStepIds;
    },
    get activeIngestTrace() {
      return activeIngestTrace;
    },
    get ingestTraceHasPrev() {
      return ingestTraceHasPrev;
    },
    get ingestTraceHasNext() {
      return ingestTraceHasNext;
    },
    get ingestTraceNavIndex() {
      return ingestTraceNavIndex;
    },
    get ingestTraceNavTotal() {
      return ingestTraceNavTotal;
    },
    loadFor,
    clearFor,
    resetOpen,
    openRetrievalTrace,
    closeRetrievalTrace,
    openIngestTrace,
    closeIngestTrace,
    prevIngestTrace: () => stepIngestTrace(-1),
    nextIngestTrace: () => stepIngestTrace(1)
  };
}

export type GraphRunTraceModel = ReturnType<typeof createGraphRunTraceModel>;
