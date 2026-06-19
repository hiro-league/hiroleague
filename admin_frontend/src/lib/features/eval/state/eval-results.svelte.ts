/**
 * Eval memory-results sub-controller — the physically isolated MEMORY-ONLY surface: per-question
 * saved status / recall-sufficiency / answered-at coverage maps, the ingested-episode ranges, the
 * benchmark-results overview, and the destructive on-disk Clear. Everything it needs about the
 * active track, the selected corpus/benchmark, the scan folder, and the live run arrives through
 * the injected `EvalResultsDeps` so it stays decoupled from the corpus picker beside it.
 */
import {
  clearEvalResults,
  listEvalBenchmarkResults,
  listEvalResults,
  type BenchmarkResultsData,
  type EvalCorpus,
  type EvalIngestedRanges
} from '$lib/api/knowledge';
import { rowFromPayload } from '$lib/features/eval/shared/eval-row';
import type { EvalTrack } from '$lib/features/eval/shared/eval-row';
import type { EvalRunController } from '$lib/features/eval/state/eval-run.svelte';

/** Narrow seam to the corpus picker + run controller, injected by the facade. */
export type EvalResultsDeps = {
  getTrack: () => EvalTrack;
  getSelectedCorpus: () => EvalCorpus | null;
  getSelectedBenchmarkId: () => string;
  getFolder: () => string;
  setError: (message: string | null) => void;
  /** The run controller — read for the live-run guard and to hand it the on-disk snapshot. */
  run: EvalRunController;
};

const EMPTY_INGESTED: EvalIngestedRanges = { ranges: [], count: 0, batches: 0, cost_usd: 0 };

export function createEvalResults(deps: EvalResultsDeps) {
  // Memory track only: per-question SAVED status, keyed by question id, from the corpus's
  // persisted results on disk. Drives the checklist coverage badges (pass/partial/fail/abstain,
  // or '' when answered-but-judge-off; ABSENT id = not-run). Kept independent of the live `rows`
  // so badges reflect saved coverage even mid-run or after a Clear.
  let savedStatusById = $state<Record<string, string>>({});
  // Per-question SAVED recall-sufficiency (judge-reported) for the recall leg — only set for JUDGED
  // rows (mark present), so an entry's absence means "not judged / unknown".
  let savedRecallSufficientById = $state<Record<string, boolean>>({});
  // Per-question SAVED eval timestamp (ISO-8601) — when each question last finished evaluating.
  let savedAnsweredAtById = $state<Record<string, string>>({});

  // Ingested-episode progress for the selected memory corpus (which turns are in the graph) —
  // drives the Corpus header's "ingested …" readout. Reset to empty on the knowledge track, no
  // corpus, or after a graph wipe (the server returns empty ranges then).
  let ingested = $state<EvalIngestedRanges>(EMPTY_INGESTED);

  // Per-corpus + TOTAL summaries for the CURRENTLY SELECTED benchmark (the Execute-tab selection —
  // no separate Report-tab benchmark picker). The table reflects every corpus in that benchmark.
  let benchmarkResults = $state<BenchmarkResultsData | null>(null);
  let benchmarkResultsLoading = $state(false);
  let benchmarkResultsError = $state<string | null>(null);

  /** Load the chosen corpus's SAVED (merged) eval results from disk (memory track).
   *
   *  Two jobs:
   *   1. Always refresh `savedStatusById` so the checklist coverage badges are current.
   *   2. When no live run is in flight, show the merged snapshot in the Results table +
   *      summary — so picking a corpus immediately shows its latest accumulated results.
   *
   *  ``applyView=false`` (used after a FAILED run) refreshes only the badges and leaves the
   *  failure banner/status intact. Knowledge track has no persisted results → clears badges. */
  async function loadResults(applyView = true) {
    if (deps.getTrack() !== 'memory') {
      resetSaved();
      ingested = EMPTY_INGESTED;
      return;
    }
    const corpus = deps.getSelectedCorpus();
    if (!corpus) {
      resetSaved();
      ingested = EMPTY_INGESTED;
      return;
    }
    try {
      const res = await listEvalResults('memory', corpus.id, corpus.questions_path);
      const data = res.data;
      const map: Record<string, string> = {};
      const rsMap: Record<string, boolean> = {};
      const aaMap: Record<string, string> = {};
      for (const r of data.rows) {
        const leg = r.legs?.recall;
        map[r.id] = leg?.mark ?? '';
        // Recall-sufficiency is only meaningful once judged (mark present); default true.
        if (leg?.mark) rsMap[r.id] = leg.recall_sufficient ?? true;
        if (r.answered_at) aaMap[r.id] = r.answered_at;
      }
      savedStatusById = map;
      savedRecallSufficientById = rsMap;
      savedAnsweredAtById = aaMap;
      // Ingested-range readout always refreshes (independent of the view guards below), so the
      // Corpus header stays accurate even mid-run or after a failed run.
      ingested = data.ingested ?? EMPTY_INGESTED;
      if (!applyView) return;
      // The live stream owns the table while a run is in flight; don't clobber it.
      if (deps.run.status === 'starting' || deps.run.status === 'running') return;
      // Hand the on-disk snapshot to the run controller, which sorts the rows, locks the leg
      // columns to the snapshot's legs (memory = ['recall']), and sets the completed/idle status.
      deps.run.applySnapshot(data.rows.map(rowFromPayload), data.summary);
    } catch (err) {
      // Saved results are best-effort enrichment — a failure just means no snapshot to show.
      console.warn('eval saved-results load failed', err);
    }
  }

  /** Load per-corpus + TOTAL summaries for the selected benchmark (memory track). No-op otherwise. */
  async function loadBenchmarkResults() {
    const bid = deps.getTrack() === 'memory' ? deps.getSelectedBenchmarkId() : '';
    if (!bid) {
      benchmarkResults = null;
      return;
    }
    benchmarkResultsLoading = true;
    benchmarkResultsError = null;
    try {
      const res = await listEvalBenchmarkResults(bid, deps.getFolder().trim());
      benchmarkResults = res.data;
    } catch (err) {
      benchmarkResultsError = err instanceof Error ? err.message : 'Failed to load benchmark results.';
      benchmarkResults = null;
    } finally {
      benchmarkResultsLoading = false;
    }
  }

  /** Clear the saved coverage maps in memory (track switch). Does NOT touch disk or `ingested`. */
  function resetSaved() {
    savedStatusById = {};
    savedRecallSufficientById = {};
    savedAnsweredAtById = {};
  }

  /** Memory: DELETE the corpus's saved results from disk (results-only — ingested memory is
   *  untouched) and clear the in-memory coverage maps. Knowledge: nothing persisted, so this is a
   *  no-op. Returns `false` (so the caller skips the view reset) only when the disk delete fails. */
  async function clearSavedResults(): Promise<boolean> {
    if (deps.getTrack() !== 'memory') return true;
    const corpus = deps.getSelectedCorpus();
    if (corpus) {
      try {
        await clearEvalResults('memory', corpus.id);
      } catch (err) {
        deps.setError(err instanceof Error ? err.message : 'Failed to clear saved results.');
        return false;
      }
    }
    resetSaved();
    return true;
  }

  return {
    get benchmarkResults() {
      return benchmarkResults;
    },
    get benchmarkResultsLoading() {
      return benchmarkResultsLoading;
    },
    get benchmarkResultsError() {
      return benchmarkResultsError;
    },
    loadBenchmarkResults,
    // Saved (persisted) per-question status for the checklist coverage badges (memory).
    // Returns the judge mark glyph, '' (answered, judge off), or undefined (not run).
    savedStatus: (id: string): string | undefined => savedStatusById[id],
    // Saved recall-sufficiency (judge-reported) for the recall leg — undefined when not judged.
    savedRecallSufficient: (id: string): boolean | undefined => savedRecallSufficientById[id],
    // Saved eval timestamp (ISO-8601) for a question — '' / undefined when not yet run.
    savedAnsweredAt: (id: string): string | undefined => savedAnsweredAtById[id],
    get savedCount() {
      return Object.keys(savedStatusById).length;
    },
    // Ingested-episode progress for the selected memory corpus (drives the Corpus header readout).
    get ingested() {
      return ingested;
    },
    loadResults,
    resetSaved,
    clearSavedResults
  };
}

export type EvalResults = ReturnType<typeof createEvalResults>;
