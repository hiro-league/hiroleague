import { apiRequest } from './client';

export const LOG_LEVELS = ['DEBUG', 'FINEINFO', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const;

/** Tier-1 operational classification of comm-path log lines. Mirrors backend TRAFFIC_CLASSES. */
export const TRAFFIC_CLASSES = [
  'inbound.message',
  'inbound.event',
  'inbound.request',
  'outbound.response',
  'outbound.lifecycle',
  'outbound.broadcast',
  'outbound.reply',
  'stream.chunk',
  'infra.event',
  'infra.transport'
] as const;
export type TrafficClass = (typeof TRAFFIC_CLASSES)[number];

export function isTrafficClass(value: string): value is TrafficClass {
  return (TRAFFIC_CLASSES as readonly string[]).includes(value);
}

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
/** The core's own streams. */
export type CoreSourceFilter = 'server' | 'channels' | 'gateway' | 'cli';
/** A Source choice: one of the core's own, or another part's stream in the core's log store (each app's `app-<name>`, the
 * phone's `device`): the logging plan's phase 6b. */
export type LogSourceFilter = CoreSourceFilter | `app-${string}` | 'device';

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
  scope_traffic_class?: string;
  scope_traffic_subclass?: string;
  has_msg_id?: boolean;
  /** The story the line belongs to and its step (W3C TraceId, SpanId), when it was logged inside one. */
  story_id?: string;
  step_id?: string;
};

export type LogsLayout = {
  /** Resolved workspace log directory (config override or `<workspace>/logs`). */
  log_dir: string;
  available_channels: string[];
  has_gateway: boolean;
  has_cli: boolean;
  /** The other parts' streams in the core's log store: `app-home`, `app-net`..., `device`. */
  other_streams: string[];
};

export type LogsTailResponse = {
  rows: LogRow[];
  file_offsets: Record<string, number>;
};

export type LogsSearchResponse = {
  rows: LogRow[];
};

export type LogsClearResponse = {
  cleared_files: string[];
};

export async function getLogsLayout(): Promise<LogsLayout> {
  return apiRequest<LogsLayout>('/logs/layout');
}

export async function tailLogs(body: {
  after_offsets?: Record<string, number> | null;
  lines?: number | null;
  last_session_only?: boolean;
  since_seconds_ago?: number | null;
}): Promise<LogsTailResponse> {
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
  trafficClasses?: TrafficClass[] | null;
};

/** Full-text search plus optional structured scope filters (AND). Requires at least one filter. */
export async function searchLogs(params: LogsSearchParams): Promise<LogsSearchResponse> {
  const sp = new URLSearchParams();
  const q = params.query?.trim();
  const deviceId = params.deviceId?.trim();
  const msgId = params.msgId?.trim();
  const method = params.method?.trim();
  const trafficClasses = (params.trafficClasses ?? []).filter(Boolean);
  if (q) sp.set('query', q);
  if (deviceId) sp.set('device_id', deviceId);
  if (msgId) sp.set('msg_id', msgId);
  if (method) sp.set('method', method);
  if (trafficClasses.length > 0) sp.set('traffic_class', trafficClasses.join(','));
  const qs = sp.toString();
  return apiRequest<LogsSearchResponse>(qs ? `/logs/search?${qs}` : '/logs/search');
}

/** Distinct JSON-RPC ``method`` values seen in the recent log tail window. */
export async function discoverLogMethods(): Promise<string[]> {
  return apiRequest<string[]>('/logs/methods');
}

export async function clearLogs(): Promise<LogsClearResponse> {
  return apiRequest<LogsClearResponse>('/logs/clear', { method: 'POST' });
}

// ---- Every part's problems and the named stories (the logging plan's phase 6b) -----------------------------------

/** A brief line, as the core's log tools give it: the time in words, the fields as a dict. */
export type BriefLogLine = {
  when: string;
  timestamp: number; // epoch seconds
  source: string;
  level: string;
  area: string;
  message: string;
  fields?: Record<string, string>;
  story_id?: string;
};

export type ProblemGroup = {
  source: string;
  level: string;
  area: string;
  count: number;
  kinds: number;
  messages: string[];
  first: string; // in words
  last: string; // in words
  story_ids: string[];
};

export type LogProblems = {
  span: string;
  total: number;
  by_source: Record<string, number>;
  groups: ProblemGroup[];
  rows: BriefLogLine[];
  truncated: boolean;
};

export type StoryKind = 'conversation' | 'event' | 'round' | 'action' | 'job';

export type StoryListItem = {
  story_id: string;
  kind: StoryKind;
  name: string;
  label: string;
  title: string;
  source: string; // the part that named it
  when: string;
  timestamp: number; // epoch seconds, its first line
  took_ms: number;
  outcome: string;
  problems: number;
  sources: string[];
};

export type LogStories = {
  span: string;
  total: number;
  by_kind: Record<string, number>;
  stories: StoryListItem[];
  truncated: boolean;
};

export type StoryStepLine = {
  step: string;
  source: string;
  elapsed_ms: number;
  outcome: string;
  when: string;
  timestamp: number; // its end, epoch seconds
  step_id: string;
  parent_step?: string;
};

export type LogStory = {
  story_id: string;
  kind: StoryKind | '';
  name: string;
  label: string;
  title: string;
  sources: string[];
  started: string;
  took_ms: number;
  problems: number;
  steps: StoryStepLine[];
  rows: BriefLogLine[];
  truncated: boolean;
};

/** Every part's warnings and errors in a span (`since`: "1h", "90m", "2d"), grouped by part, level and area. */
export async function getLogProblems(since: string): Promise<LogProblems> {
  return apiRequest<LogProblems>(`/logs/problems?since=${encodeURIComponent(since)}`);
}

/** The named stories of a span across every part, newest first. */
export async function getLogStories(params: { since: string; kind?: string; source?: string; problems?: boolean }): Promise<LogStories> {
  const sp = new URLSearchParams({ since: params.since, limit: '300' });
  if (params.kind) sp.set('kind', params.kind);
  if (params.source) sp.set('source', params.source);
  if (params.problems) sp.set('problems', 'true');
  return apiRequest<LogStories>(`/logs/stories?${sp.toString()}`);
}

/** One story across every part: what it is, its steps and its lines. */
export async function getLogStory(storyId: string): Promise<LogStory> {
  return apiRequest<LogStory>(`/logs/stories/${encodeURIComponent(storyId)}`);
}

/** The Logs page's time window as a span the log tools read ("Last session" reads the last day). */
export function logWindowSpan(lastSessionOnly: boolean, range: LogTimeRange): string {
  if (lastSessionOnly) return '1d';
  const seconds = logTimeRangeSeconds(range);
  return seconds === null ? '30d' : `${Math.round(seconds / 60)}m`;
}
