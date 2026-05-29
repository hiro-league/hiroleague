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
