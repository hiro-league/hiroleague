import { apiRequest, type ApiResponse } from './client';

export type GraphLedgerRow = {
  id: string;
  ts: number | '';
  run_id: string;
  step_index: number | '';
  node: string;
  node_attempt: number | '';
  branch_index: number | '';
  status: string;
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
  stt_audio_seconds: number | '';
  tts_audio_seconds: number | '';
  cost_usd: number | '';
  pricing_version: string;
  decision_kind: string;
  decision_detail: string;
  error_code: string;
};

export type GraphRunsTailResponse = {
  rows: GraphLedgerRow[];
  file_offsets: Record<string, number>;
};

export async function tailGraphRuns(body: {
  after_offsets?: Record<string, number> | null;
  lines?: number | null;
  since_seconds_ago?: number | null;
  filters?: Record<string, string>;
}): Promise<ApiResponse<GraphRunsTailResponse>> {
  return apiRequest<GraphRunsTailResponse>('/graph-runs/tail', {
    method: 'POST',
    body
  });
}

export type GraphRunInspectResponse = {
  rows: GraphLedgerRow[];
  langsmith_url?: string | null;
};

export async function getGraphRun(runId: string): Promise<ApiResponse<GraphRunInspectResponse>> {
  return apiRequest<GraphRunInspectResponse>(`/graph-runs/${encodeURIComponent(runId)}`);
}
