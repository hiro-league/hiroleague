import { apiRequest, type ApiResponse } from './client';

export const LOG_LEVELS = ['DEBUG', 'FINEINFO', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const;

/** Past-window options for live tail (ignored when ``last_session_only``). */
export const LOG_TIME_RANGES = ['1h', '2h', '4h', '1d', '2d', '3d', 'all'] as const;
export type LogTimeRange = (typeof LOG_TIME_RANGES)[number];

export function logTimeRangeSeconds(range: LogTimeRange): number | null {
  switch (range) {
    case '1h':
      return 3600;
    case '2h':
      return 7200;
    case '4h':
      return 14400;
    case '1d':
      return 86400;
    case '2d':
      return 172800;
    case '3d':
      return 259200;
    case 'all':
      return null;
    default: {
      const _x: never = range;
      return _x;
    }
  }
}

export type LogLevel = (typeof LOG_LEVELS)[number];
export type LogSourceFilter = 'server' | 'channels' | 'gateway' | 'cli';
export type LogSortOrder = 'newest' | 'oldest';

export type LogExtraSegment = {
  key: string | null;
  value: string;
  pretty: string | null;
};

export type LogRow = {
  id: string;
  timestamp: number;
  timestamp_display: string;
  date_display: string;
  source: string;
  level: LogLevel | string;
  level_html: string;
  module: string;
  module_html: string;
  message: string;
  message_html: string;
  message_pretty: string | null;
  extra: string;
  extra_html: string;
  extra_tooltip_html: string;
  extra_segments: LogExtraSegment[];
  is_startup: boolean;
  /** Parsed from CSV ``extra`` — structured log scope (device / message / RPC method). */
  scope_device_id?: string;
  scope_msg_id?: string;
  scope_method?: string;
  scope_text_preview?: string;
  has_msg_id?: boolean;
};

export type LogsLayout = {
  available_channels: string[];
  has_gateway: boolean;
  has_cli: boolean;
};

export type LogsTailResponse = {
  rows: LogRow[];
  file_offsets: Record<string, number>;
};

export type LogsSearchResponse = {
  rows: LogRow[];
};

export async function getLogsLayout(): Promise<ApiResponse<LogsLayout>> {
  return apiRequest<LogsLayout>('/logs/layout');
}

export async function tailLogs(body: {
  after_offsets?: Record<string, number> | null;
  lines?: number | null;
  last_session_only?: boolean;
  since_seconds_ago?: number | null;
}): Promise<ApiResponse<LogsTailResponse>> {
  return apiRequest<LogsTailResponse>('/logs/tail', {
    method: 'POST',
    body
  });
}

export type LogsSearchParams = {
  query?: string;
  deviceId?: string | null;
  msgId?: string | null;
  method?: string | null;
};

/** Full-text search plus optional structured scope filters (AND). Requires at least one filter. */
export async function searchLogs(params: LogsSearchParams): Promise<ApiResponse<LogsSearchResponse>> {
  const sp = new URLSearchParams();
  const q = params.query?.trim();
  const deviceId = params.deviceId?.trim();
  const msgId = params.msgId?.trim();
  const method = params.method?.trim();
  if (q) sp.set('query', q);
  if (deviceId) sp.set('device_id', deviceId);
  if (msgId) sp.set('msg_id', msgId);
  if (method) sp.set('method', method);
  const qs = sp.toString();
  return apiRequest<LogsSearchResponse>(qs ? `/logs/search?${qs}` : '/logs/search');
}

/** Distinct JSON-RPC ``method`` values seen in the recent log tail window. */
export async function discoverLogMethods(): Promise<ApiResponse<string[]>> {
  return apiRequest<string[]>('/logs/methods');
}
