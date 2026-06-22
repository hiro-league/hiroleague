import { apiRequest, type ApiResponse } from './client';

export type GraphLedgerRow = {
  id: string;
  ts: number | '';
  run_id: string;
  step_index: number | '';
  /** Sub-step ordinal within step_index for nested rows; rendered as `${step_index}.${sub_step}`. */
  sub_step: number | '';
  node: string;
  node_attempt: number | '';
  branch_index: number | '';
  status: string;
  row_kind: 'node' | 'run' | string;
  elapsed_ms: number | '';
  inbound_id: string;
  chat_channel_id: number | '';
  device_id: string;
  user_id: string;
  character_id: string;
  provider: string;
  model: string;
  input_tokens: number | '';
  output_tokens: number | '';
  cached_input_tokens: number | '';
  reasoning_tokens: number | '';
  tts_chars: number | '';
  tts_text_tokens: number | '';
  tts_audio_tokens: number | '';
  stt_audio_seconds: number | '';
  stt_audio_tokens: number | '';
  tts_audio_seconds: number | '';
  cost_usd: number | '';
  pricing_version: string;
  decision_kind: string;
  decision_detail: string;
  input_preview: string;
  output_preview: string;
  error_code: string;
};

export type GraphRunsTailResponse = {
  rows: GraphLedgerRow[];
  file_offsets: Record<string, number>;
  has_more: boolean;
};

export const GRAPH_RUNS_PAGE_SIZE = 100;

export async function tailGraphRuns(body: {
  after_offsets?: Record<string, number> | null;
  lines?: number | null;
  since_seconds_ago?: number | null;
  skip_from_end?: number | null;
  filters?: Record<string, string>;
}): Promise<ApiResponse<GraphRunsTailResponse>> {
  return apiRequest<GraphRunsTailResponse>('/graph-runs/tail', {
    method: 'POST',
    body
  });
}

export type GraphRunInspectResponse = {
  rows: GraphLedgerRow[];
  /** Latest `row_kind=run` line for this run_id (null for legacy logs without aggregate rows). */
  aggregate: GraphLedgerRow | null;
};

export type GraphRunLangsmithUrlResponse = {
  langsmith_url: string | null;
};

/** Same column order as `GRAPH_LEDGER_COLUMNS` on the server; `'id'` is appended (derived id). */

export const GRAPH_RUN_HEADER_FIELDS = [
  'ts',
  'run_id',
  'step_index',
  'sub_step',
  'node',
  'node_attempt',
  'branch_index',
  'status',
  'elapsed_ms',
  'inbound_id',
  'chat_channel_id',
  'device_id',
  'user_id',
  'character_id',
  'provider',
  'model',
  'input_tokens',
  'output_tokens',
  'cached_input_tokens',
  'reasoning_tokens',
  'tts_chars',
  'tts_text_tokens',
  'tts_audio_tokens',
  'stt_audio_seconds',
  'stt_audio_tokens',
  'tts_audio_seconds',
  'cost_usd',
  'pricing_version',
  'decision_kind',
  'decision_detail',
  'error_code',
  'row_kind',
  'input_preview',
  'output_preview',
  'id'
] as const satisfies ReadonlyArray<keyof GraphLedgerRow>;

/** Aggregate header on the single-run tab: ledger minus fields shown in the toolbar or redundant (run id in title). */

export const GRAPH_RUN_HEADER_TAB_FIELDS = GRAPH_RUN_HEADER_FIELDS.filter(
  (k) =>
    k !== 'step_index' &&
    k !== 'sub_step' &&
    k !== 'node_attempt' &&
    k !== 'branch_index' &&
    k !== 'pricing_version' &&
    k !== 'status' &&
    k !== 'input_preview' &&
    k !== 'output_preview' &&
    k !== 'run_id' &&
    k !== 'id' &&
    k !== 'inbound_id' &&
    k !== 'cost_usd' &&
    k !== 'chat_channel_id' &&
    k !== 'character_id' &&
    k !== 'node' &&
    k !== 'elapsed_ms' &&
    k !== 'row_kind' &&
    k !== 'input_tokens' &&
    k !== 'output_tokens' &&
    k !== 'cached_input_tokens' &&
    k !== 'reasoning_tokens' &&
    k !== 'provider' &&
    k !== 'model' &&
    k !== 'tts_chars' &&
    k !== 'tts_text_tokens' &&
    k !== 'tts_audio_tokens' &&
    k !== 'stt_audio_seconds' &&
    k !== 'stt_audio_tokens' &&
    k !== 'tts_audio_seconds'
) satisfies ReadonlyArray<keyof GraphLedgerRow>;

/** Per-node ledger cells only; leading columns emphasize step, identity, timing, billing, routing. */

export const GRAPH_RUN_NODE_TABLE_FIELDS = [
  'step_index',
  'node',
  'status',
  'elapsed_ms',
  'cost_usd',
  'decision_kind',
  'decision_detail',
  'provider',
  'model',
  'error_code'
] as const satisfies ReadonlyArray<keyof GraphLedgerRow>;

export async function getGraphRun(runId: string): Promise<ApiResponse<GraphRunInspectResponse>> {
  return apiRequest<GraphRunInspectResponse>(`/graph-runs/${encodeURIComponent(runId)}`);
}

/** LangSmith URL is fetched separately — inspect avoids blocking on upstream LangSmith latency. */

export async function getGraphRunLangsmithUrl(
  runId: string
): Promise<ApiResponse<GraphRunLangsmithUrlResponse>> {
  return apiRequest<GraphRunLangsmithUrlResponse>(
    `/graph-runs/${encodeURIComponent(runId)}/langsmith-url`
  );
}

// ── Retrieval stage trace (Graphiti fact search) ────────────────────────────
// Full per-stage data (candidate legs / hop / rank / temporal) recorded by the
// re-hosted search pipeline when tracing is enabled, read from the JSONL sidecar.

/** One fact edge as it flows through a stage (the eval-relevant metadata). */
/**
 * One item flowing out of a stage. The populated fields depend on the stage `lane`:
 *   - `edge` (facts): `fact`, `name` (relation), `episodes`, `valid_at`/`invalid_at`/`expired_at`.
 *   - `node` (entities): `name`, `entity_type`, `summary`.
 *   - `episode` (turns): `content`, `source`, `valid_at`.
 * `uuid` and `score` are common. Lane-foreign fields are simply absent.
 */
export type RetrievalTraceItem = {
  uuid: string;
  // edge lane
  fact?: string;
  name?: string;
  source_node_uuid?: string;
  target_node_uuid?: string;
  episodes?: string[];
  valid_at?: string | null;
  invalid_at?: string | null;
  expired_at?: string | null;
  // node lane
  entity_type?: string;
  summary?: string;
  // episode lane
  content?: string;
  source?: string;
  source_description?: string;
  /** Stage score when one exists (fused / reranked); null on raw bm25/cosine legs. */
  score: number | null;
};

/** One pipeline stage: `embed` | `candidate` (per leg) | `hop` | `rank` | `temporal`. */
export type RetrievalTraceStage = {
  kind: string;
  label: string;
  /** Entity type the stage belongs to: `edge` | `node` | `episode` | `query` (embed). */
  lane: string;
  elapsed_ms: number;
  meta: Record<string, unknown>;
  items: RetrievalTraceItem[];
};

/** One full fact search, tagged with the `step_index` of its `graph_expand` row. */
export type RetrievalTraceRecord = {
  run_id: string;
  step_index: number | '';
  /** Agentic-retrieval sub-query id this trace belongs to; null/absent for non-agentic recall. */
  sid?: number | null;
  schema_version: number;
  query: string;
  group_id: string;
  recipe: string;
  temporal: string;
  num_results: number;
  sim_min_score: number;
  k_hop: number;
  started_at: number;
  stages: RetrievalTraceStage[];
};

export type GraphRunRetrievalTraceResponse = {
  traces: RetrievalTraceRecord[];
};

/** Per-stage fact-search traces for a run (empty when tracing wasn't enabled). */
export async function getGraphRunRetrievalTrace(
  runId: string
): Promise<ApiResponse<GraphRunRetrievalTraceResponse>> {
  return apiRequest<GraphRunRetrievalTraceResponse>(
    `/graph-runs/${encodeURIComponent(runId)}/retrieval-trace`
  );
}

// ── Ingest stage trace (Graphiti add_episode) ───────────────────────────────
// Full per-stage data (prompt IN / structured result OUT) for each add_episode
// stage — extract entities → resolve/dedupe → extract facts → date facts →
// resolve/invalidate facts → summarize — recorded by the LLM adapter when ingest
// tracing is enabled, plus the persisted result (what actually landed in the graph).

/** One prompt message of a stage's input (the model context the step ran on). */
export type IngestTraceMessage = { role: string; content: string };

/** A persisted entity node (what add_episode wrote to the graph). */
export type IngestTraceNode = {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  score: number | null;
};

/** A persisted fact edge (relationship triple) with its bi-temporal window. */
export type IngestTraceEdge = {
  uuid: string;
  fact: string;
  name: string;
  source_node_uuid: string;
  target_node_uuid: string;
  episodes: string[];
  valid_at: string | null;
  invalid_at: string | null;
  expired_at: string | null;
  score: number | null;
};

/**
 * One `add_episode` stage. `source` is `llm` for a captured model call (the common
 * case) or `dedup` for a non-LLM auto-merge. `input` is the prompt messages for an
 * LLM stage; `output` is the structured result (parsed model dump / dedup decision).
 */
export type IngestTraceStage = {
  node: string;
  label: string;
  operation: string;
  source: string;
  elapsed_ms: number;
  input_tokens: number;
  output_tokens: number;
  model_id: string;
  meta: Record<string, unknown>;
  input: IngestTraceMessage[] | unknown;
  output: unknown;
};

/** Active ontology legend: `entity_type_id` → type name + description (graphiti's id ordering,
 *  id 0 = base `Entity`). Lets the dialog resolve `extract_entities`' numeric ids to real types. */
export type IngestEntityType = {
  id: number;
  name: string;
  description: string;
};

/** One episode's full ingest trace, tagged with the `step_index` of its episode row. */
export type IngestTraceRecord = {
  run_id: string;
  step_index: number | '';
  schema_version: number;
  chunk_id: string;
  episode_index: number;
  total: number;
  name: string;
  text: string;
  group_id: string;
  reference_time: string;
  started_at: number;
  invalidated_count: number;
  /** Ontology legend for resolving `extract_entities` type ids (absent on pre-legend sidecars). */
  entity_types?: IngestEntityType[];
  persisted_nodes: IngestTraceNode[];
  persisted_edges: IngestTraceEdge[];
  stages: IngestTraceStage[];
};

export type GraphRunIngestTraceResponse = {
  traces: IngestTraceRecord[];
};

/** Per-stage add_episode traces for a run (empty when tracing wasn't enabled). */
export async function getGraphRunIngestTrace(
  runId: string
): Promise<ApiResponse<GraphRunIngestTraceResponse>> {
  return apiRequest<GraphRunIngestTraceResponse>(
    `/graph-runs/${encodeURIComponent(runId)}/ingest-trace`
  );
}
