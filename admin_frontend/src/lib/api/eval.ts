import { apiRequest, type ApiResponse } from './client';
import type {
  EvalCompletedPayload,
  EvalQuestionPayload,
  EvalRunStateData
} from '$lib/features/eval/shared/eval-events';

/** L3 (Phase 5e) — kick the synthetic eval batch. Returns the run_id
 *  immediately; progress streams on /api/knowledge/events. */
export type EvalRunRequest = {
  // Eval track: 'knowledge' (document/chunk corpus → flat vs graphiti) or
  // 'memory' (turn corpus → conversation remember/recall, single recall leg).
  track?: 'knowledge' | 'memory';
  // Chosen corpus (from the picker). id doubles as the eval drawer suffix.
  corpus_id?: string;
  corpus_path?: string;
  questions_path?: string;
  // knowledge: ingest the doc corpus first. memory: remember the turn corpus first.
  ingest_synthetic?: boolean;
  build_graph?: boolean; // knowledge only
  // Memory track — explicitly wipe the eval graph before remembering (decoupled from remember,
  // so a corpus can be built across appended batches). Default off ⇒ never clear implicitly.
  clear_before?: boolean;
  // Memory track — remember-phase episode window: start index + max count into the corpus.
  // 0 / null = from the start / to the end. Lets a large corpus be remembered in chunks.
  episode_offset?: number;
  episode_limit?: number | null;
  judge?: boolean; // run the optional LLM judge (grade answers vs the ideal)
  // Memory track — max questions running recall→answer→judge at once (1 = serial).
  // Clamped server-side to [1, 8]; ignored on the knowledge track.
  question_concurrency?: number;
  // REQUIRED, non-empty — the UI forces an explicit question selection (no "run all").
  question_ids?: string[];
  // Knowledge only — legs to compare, subset of ['flat','graphiti']. Empty/undefined = both.
  modes?: string[];
  run_id?: string;
};

export function runKnowledgeEval(req: EvalRunRequest = {}): Promise<ApiResponse<{ run_id: string }>> {
  return apiRequest<{ run_id: string }>('/eval/run', {
    method: 'POST',
    body: req,
    timeoutMs: 30000  // setup can take a few seconds; the eval itself runs in the background
  });
}

/** L3 — replay the latest eval run's live state for the workspace (server-side
 *  store). The panel calls this on mount so navigation + cross-origin (Vite vs
 *  packaged UI) both show the same run. ``data`` is null when no run exists. */
export function getKnowledgeEvalState(): Promise<ApiResponse<EvalRunStateData | null>> {
  return apiRequest<EvalRunStateData | null>('/eval/state', {
    method: 'GET',
    timeoutMs: 15000
  });
}

/** L3 — request cancellation of the in-flight eval run. The runner emits a
 *  terminal ``eval.cancelled`` event once it stops. */
export function cancelKnowledgeEval(
  runId?: string | null
): Promise<ApiResponse<{ cancelled: boolean; run_id: string | null }>> {
  return apiRequest<{ cancelled: boolean; run_id: string | null }>('/eval/cancel', {
    method: 'POST',
    body: { run_id: runId ?? null },
    timeoutMs: 15000
  });
}

/** One discovered corpus in the picker (a turn corpus file, or a doc-corpus folder). */
export type EvalCorpus = {
  id: string;
  name: string;
  corpus_path: string;
  questions_path: string;
  question_count: number;
  item_count: number; // episodes (memory) or .md docs (knowledge)
  has_graph: boolean; // a graph is already built for this corpus (drives the Rebuild-graph default + wipe warning)
  ingested_count?: number; // memory track: distinct episodes ingested into the graph (vs item_count) → status dot

  // Benchmark grouping — memory track only (from eval/benchmarks.yaml). Absent on knowledge-track
  // corpuses, which aren't grouped. `label` is the display name (falls back to id server-side).
  benchmark?: string; // benchmark id, e.g. "locomo"
  benchmark_label?: string; // human-readable benchmark name, e.g. "LoCoMo"
  label?: string; // human-readable corpus name shown in the Corpus dropdown
};

/** List the corpuses found in a folder for a track (the corpus-picker dropdown source). */
export function listEvalCorpuses(
  track: 'memory' | 'knowledge',
  folder = ''
  // ``log_dir`` is the workspace's absolute ``logs/`` dir (the ledger sidecar root) — used by
  // the eval "Copy for AI" brief to point an agent at retrieval_trace/ingest_trace/graph.log.
  // Empty when the workspace can't be resolved (brief then falls back to relative paths).
): Promise<ApiResponse<{ track: string; folder: string; corpuses: EvalCorpus[]; log_dir?: string }>> {
  const qs = new URLSearchParams({ track });
  if (folder) qs.set('folder', folder);
  return apiRequest<{ track: string; folder: string; corpuses: EvalCorpus[]; log_dir?: string }>(
    `/eval/corpuses?${qs.toString()}`,
    { method: 'GET', timeoutMs: 15000 }
  );
}

/** One row in the eval question bank (for the checklist). */
export type EvalQuestionItem = {
  id: string;
  category: string;
  subcategory: string;
  difficulty?: string; // medium/hard/very_hard — shown as a chip in the picker
  question: string;
  requires_graph: boolean;
  expected_answer?: string;
};

/** One episode (turn) in a memory-track corpus — the unit shown in the Corpus review transcript. */
export type EvalEpisode = {
  id: string;
  timestamp: string; // ISO-8601 (the dated turn)
  speaker: string;
  type: string;
  body: string;
};

/** A memory corpus's episodes + light meta (count + date span), for the Corpus review panel. */
export type EvalCorpusData = {
  path: string;
  episode_count: number;
  first_timestamp: string;
  last_timestamp: string;
  episodes: EvalEpisode[];
};

/** Load a memory corpus's episodes by its <id>.episodes.jsonl path (the Corpus review source). */
export function getEvalCorpus(path: string): Promise<ApiResponse<EvalCorpusData>> {
  return apiRequest<EvalCorpusData>(
    `/eval/corpus?path=${encodeURIComponent(path)}`,
    { method: 'GET', timeoutMs: 15000 }
  );
}

/** One episode's at-ingest extraction summary — counts of entities/facts the ingestion produced,
 *  plus where to find its ingest-pipeline trace (run_id + step_index). entity_count === fact_count
 *  === 0 means the episode extracted nothing into the graph. */
export type CorpusEpisodeExtraction = {
  entity_count: number;
  fact_count: number;
  run_id: string;
  step_index: number | '';
};

/** Per-episode extraction map for a corpus, keyed by episode id. Empty when the corpus was
 *  ingested with graph tracing off (observability !== 'trace') or hasn't been remembered yet.
 *  `group_id` is the eval graph partition (e.g. `eval_mem_beam128k_13`), for deep-linking an
 *  episode into the graph view (group + chunk_id filter). */
export type CorpusExtractionData = {
  episodes: Record<string, CorpusEpisodeExtraction>;
  group_id: string;
};

/** Per-episode at-ingest extraction counts for a memory corpus (by corpus id, e.g. `beam128k_13`),
 *  read from its ingest-trace sidecars in the selected workspace. Drives the Corpus tab's
 *  extracted/not badge + "ingest pipeline" button. */
export function getCorpusIngestExtraction(
  corpusId: string
): Promise<ApiResponse<CorpusExtractionData>> {
  return apiRequest<CorpusExtractionData>(
    `/eval/corpus-extraction?corpus_id=${encodeURIComponent(corpusId)}`,
    { method: 'GET', timeoutMs: 15000 }
  );
}

/** List a corpus's question bank by its <id>.questions.yaml path (the checklist source). */
export function listEvalQuestions(
  path: string
): Promise<ApiResponse<{ path: string; questions: EvalQuestionItem[] }>> {
  return apiRequest<{ path: string; questions: EvalQuestionItem[] }>(
    `/eval/questions?path=${encodeURIComponent(path)}`,
    { method: 'GET', timeoutMs: 15000 }
  );
}

/** Persisted per-corpus eval results (memory track) — the merged snapshot the panel
 *  shows when a corpus is picked. ``rows`` is bank-ordered; ``summary`` is recomputed
 *  over the whole accumulated set. Both empty when nothing's been saved yet. */
/** Ingested-episode progress for a memory corpus — which turns have been remembered into the
 *  graph. `ranges` are sorted, INCLUSIVE [start, end] episode-index spans (coalesced, gaps
 *  preserved); `count` is distinct episodes ingested; `batches` is how many remember runs. */
export type EvalIngestedRanges = {
  ranges: [number, number][];
  count: number;
  batches: number;
  // Cumulative per-corpus ingest (graph-build) spend in USD — summed across every remember batch.
  // The only place ingest cost survives a reload (per-question rows never carry it). 0 when unset.
  cost_usd?: number;
};

export type EvalResultsData = {
  rows: EvalQuestionPayload[];
  summary: EvalCompletedPayload | null;
  // Absent on the knowledge track (memory-only); defaults to empty when unset.
  ingested?: EvalIngestedRanges;
};

export type EvalLocomoExportData = {
  filename: string;
  content: string;
  exported_count: number;
  total_count: number;
  prediction_key: string;
  partial: boolean;
};

/** Load a corpus's saved eval results (memory track). ``questionsPath`` lets the
 *  server spine the rows on the current bank (fresh question text + bank order). */
export function listEvalResults(
  track: 'memory' | 'knowledge',
  corpusId: string,
  questionsPath = ''
): Promise<ApiResponse<EvalResultsData>> {
  const qs = new URLSearchParams({ track, corpus_id: corpusId });
  if (questionsPath) qs.set('questions_path', questionsPath);
  return apiRequest<EvalResultsData>(`/eval/results?${qs.toString()}`, {
    method: 'GET',
    timeoutMs: 15000
  });
}

/** Resolve ONE saved memory-eval question row by its per-question graph ``run_id``. Backs the
 *  Graph-Runs → eval-detail bridge (a ``memory_recall`` node carries that run_id). ``row`` is null
 *  when no saved row ran under that id (e.g. results cleared, or graph tracing only). */
export function getEvalRowByRunId(
  runId: string
): Promise<ApiResponse<{ row: EvalQuestionPayload | null }>> {
  const qs = new URLSearchParams({ run_id: runId });
  return apiRequest<{ row: EvalQuestionPayload | null }>(`/eval/row?${qs.toString()}`, {
    method: 'GET',
    timeoutMs: 15000
  });
}

/** One corpus's row in the benchmark results summary table. ``summary`` is the same
 *  aggregate the per-corpus Report uses (null until the corpus has saved rows). */
export type BenchmarkCorpusResult = {
  corpus_id: string;
  label: string;
  bank_questions: number; // questions in the corpus bank
  item_count: number; // episodes in the corpus
  answered: number; // saved (run) question rows
  has_results: boolean;
  summary: EvalCompletedPayload | null;
};

/** Benchmark-grouped memory-eval results: one summary per corpus + a TOTAL over all rows. */
export type BenchmarkResultsData = {
  benchmark: { id: string; label: string };
  corpuses: BenchmarkCorpusResult[];
  total: EvalCompletedPayload | null;
};

/** Load per-corpus + TOTAL summaries for every corpus in a benchmark (memory track). */
export function listEvalBenchmarkResults(
  benchmark: string,
  folder = ''
): Promise<ApiResponse<BenchmarkResultsData>> {
  const qs = new URLSearchParams({ benchmark });
  if (folder) qs.set('folder', folder);
  return apiRequest<BenchmarkResultsData>(`/eval/results/by-benchmark?${qs.toString()}`, {
    method: 'GET',
    timeoutMs: 20000
  });
}

/** Delete a corpus's saved eval results from disk (results-only; the ingested memory
 *  drawer is left intact). Memory track only. */
export function clearEvalResults(
  track: 'memory' | 'knowledge',
  corpusId: string
): Promise<ApiResponse<{ removed: number }>> {
  return apiRequest<{ removed: number }>('/eval/results/clear', {
    method: 'POST',
    body: { track, corpus_id: corpusId },
    timeoutMs: 15000
  });
}

/** Downloadable LoCoMo-compatible JSON export for saved memory-eval results. */
export function exportEvalResultsLocomo(
  corpusId: string,
  questionsPath: string,
  predictionKey = 'hiro_memory_prediction'
): Promise<ApiResponse<EvalLocomoExportData>> {
  const qs = new URLSearchParams({
    corpus_id: corpusId,
    questions_path: questionsPath,
    prediction_key: predictionKey
  });
  return apiRequest<EvalLocomoExportData>(`/eval/results/locomo?${qs.toString()}`, {
    method: 'GET',
    timeoutMs: 30000
  });
}
