import { apiRequest, type ApiResponse } from './client';

export const LOG_LEVELS = ['DEBUG', 'FINEINFO', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const;

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
}): Promise<ApiResponse<LogsTailResponse>> {
  return apiRequest<LogsTailResponse>('/logs/tail', {
    method: 'POST',
    body
  });
}

export async function searchLogs(query: string): Promise<ApiResponse<LogsSearchResponse>> {
  return apiRequest<LogsSearchResponse>(
    `/logs/search?query=${encodeURIComponent(query)}`
  );
}
