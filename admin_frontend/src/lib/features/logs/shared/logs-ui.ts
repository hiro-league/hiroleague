import {
  LOG_LEVELS,
  LOG_TIME_RANGES,
  type LogExtraSegment,
  type LogLevel,
  type LogRow,
  type LogSourceFilter,
  type LogTimeRange,
  type LogsLayout,
  type TrafficClass
} from '$lib/api/logs';
import type { DeviceRow } from '$lib/api/channels-devices';

/** Session-backed shape for logs UI (persisted fields only). */
export type LogsPrefsSnapshot = {
  paused?: boolean;
  sortOrder?: 'newest' | 'oldest';
  activeSources?: LogSourceFilter[];
  activeChannels?: string[];
  activeChannel?: string;
  levelFilter?: LogLevel[];
  searchText?: string;
  scopeDeviceId?: string;
  scopeMsgId?: string;
  scopeMethod?: string;
  trafficClassFilter?: TrafficClass[];
  detailPanelOpen?: boolean;
  controlsCollapsed?: boolean;
  /** Default true — tail from latest ``🚀 Hiro Server starting`` (server.log). */
  lastSessionOnly?: boolean;
  /** Rolling window when ``last_session_only`` is false; default ``1h``. */
  logTimeRange?: LogTimeRange;
};

export type RenderLogRow = LogRow & { _rowKey: string };

export const LOGS_PREF_SESSION_KEY = 'hiro.admin.logs';

export const SOURCE_LABELS: Record<LogSourceFilter, string> = {
  server: 'Server',
  channels: 'Channels',
  gateway: 'Gateway',
  cli: 'CLI'
};

/** Map API log row ``source`` field to the filter bucket (for icons / chip alignment). */
export function logRowSourceFilter(rowSource: string): LogSourceFilter | null {
  if (rowSource === 'server' || rowSource === 'gateway' || rowSource === 'cli') {
    return rowSource;
  }
  if (rowSource.startsWith('channel-')) {
    return 'channels';
  }
  return null;
}

/** Human label aligned with filter chip names; channel rows append `` · `` + channel id. */
export function logRowSourceLabel(rowSource: string): string {
  const filter = logRowSourceFilter(rowSource);
  if (filter === 'channels') {
    const channel = rowSource.replace(/^channel-/, '');
    return channel ? `${SOURCE_LABELS.channels} · ${channel}` : SOURCE_LABELS.channels;
  }
  if (filter) {
    return SOURCE_LABELS[filter];
  }
  return rowSource.trim() || '—';
}

function formatExtraSegmentsForClipboard(segments: LogExtraSegment[]): string {
  if (segments.length === 0) return '—';
  return segments
    .map((seg) => {
      const title = seg.key ?? 'value';
      const body = (seg.pretty ?? seg.value).trim() || '—';
      return `${title}:\n${body}`;
    })
    .join('\n\n');
}

/** Plain-text snapshot of the log details panel (matches on-screen sections) for clipboard export. */
export function formatLogDetailsClipboardText(row: RenderLogRow): string {
  const message =
    row.message_pretty?.trim() ? row.message_pretty : row.message?.trim() ? row.message : '—';

  const parts = [
    `Level: ${row.level}`,
    `Source: ${logRowSourceLabel(row.source)}`,
    `Module: ${row.module || '—'}`,
    `Message:\n${message}`,
    `Device scope: ${row.scope_device_id ?? '—'}`,
    `Request method scope: ${row.scope_method ?? '—'}`
  ];

  // Same visibility rule as ``LogsDetailPanel`` message text preview block.
  if (row.scope_msg_id || (row.scope_text_preview ?? '').trim()) {
    const previewBody = (row.scope_text_preview ?? '').trim() ? row.scope_text_preview! : 'N/A';
    parts.push(`Message text preview:\n${previewBody}`);
  }

  parts.push(`Extra:\n${formatExtraSegmentsForClipboard(row.extra_segments)}`);
  parts.push(`Message scope: ${row.scope_msg_id ?? '—'}`);
  parts.push(`Timestamp (epoch): ${row.timestamp}`);
  parts.push(`When: ${row.date_display} · ${row.timestamp_display}`);

  return parts.join('\n\n');
}

export function sourcesForLayout(nextLayout: LogsLayout | null): LogSourceFilter[] {
  const sources: LogSourceFilter[] = ['server', 'channels'];
  if (nextLayout?.has_gateway) sources.push('gateway');
  if (nextLayout?.has_cli) sources.push('cli');
  return sources;
}

export function isLogSourceFilter(value: string): value is LogSourceFilter {
  return value === 'server' || value === 'channels' || value === 'gateway' || value === 'cli';
}

export function isLogLevel(value: string): value is LogLevel {
  return LOG_LEVELS.includes(value as LogLevel);
}

export function isLogTimeRange(value: string): value is LogTimeRange {
  return (LOG_TIME_RANGES as readonly string[]).includes(value);
}

export function withRenderKeys(logRows: LogRow[], startIndex = 0): RenderLogRow[] {
  return logRows.map((row, index) => ({
    ...row,
    _rowKey: `${row.id}:${startIndex + index}`
  }));
}

/**
 * ``_rowKey`` is ``${row.id}:${batchIndex}``; log ``id`` from the API is stable across tail reloads,
 * but the numeric suffix changes when the row appears at a different index — strip it for reconciliation.
 */
export function logIdFromRowKey(rowKey: string): string {
  const lastColon = rowKey.lastIndexOf(':');
  if (lastColon < 0) return rowKey;
  const tail = rowKey.slice(lastColon + 1);
  if (/^\d+$/.test(tail)) return rowKey.slice(0, lastColon);
  return rowKey;
}

export type RowFilterContext = {
  activeSources: LogSourceFilter[];
  activeChannel: string;
  levelFilter: LogLevel[];
  trafficClassFilter: TrafficClass[];
};

export function rowPassesFilters(row: LogRow, ctx: RowFilterContext): boolean {
  if (row.source === 'server' && !ctx.activeSources.includes('server')) return false;
  if (row.source === 'gateway' && !ctx.activeSources.includes('gateway')) return false;
  if (row.source === 'cli' && !ctx.activeSources.includes('cli')) return false;
  if (row.source.startsWith('channel-')) {
    if (!ctx.activeSources.includes('channels')) return false;
    const channel = row.source.replace(/^channel-/, '');
    if (ctx.activeChannel && ctx.activeChannel !== channel) return false;
  }
  if (ctx.levelFilter.length > 0 && !ctx.levelFilter.includes(row.level as LogLevel)) return false;
  if (ctx.trafficClassFilter.length > 0) {
    const rowTc = (row.scope_traffic_class ?? '').trim();
    if (!rowTc || !ctx.trafficClassFilter.includes(rowTc as TrafficClass)) return false;
  }
  return true;
}

export function deviceLabelFor(devices: DeviceRow[], deviceUuid: string): string {
  const row = devices.find((d) => d.device_id === deviceUuid);
  const name = row?.device_name?.trim();
  if (name) return name;
  return deviceUuid.length > 12 ? `${deviceUuid.slice(0, 8)}…` : deviceUuid;
}

export function shortMsgId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 10)}…` : id;
}

/** Short, distinct labels for traffic_class chips. */
export const TRAFFIC_CLASS_LABELS: Record<TrafficClass, string> = {
  'inbound.message': 'In · message',
  'inbound.event': 'In · event',
  'inbound.request': 'In · request',
  'outbound.response': 'Out · response',
  'outbound.lifecycle': 'Out · lifecycle',
  'outbound.broadcast': 'Out · broadcast',
  'outbound.reply': 'Out · reply',
  'stream.chunk': 'Stream',
  'infra.event': 'Infra · event',
  'infra.transport': 'Infra · transport'
};

/** Tailwind class for the traffic_class chip in the table column. Cool=in, warm=out, neutral=infra/stream. */
export function trafficClassChipClass(tc: string): string {
  if (tc.startsWith('inbound.')) {
    return 'border-sky-400/40 bg-sky-500/15 text-sky-700 dark:text-sky-300';
  }
  if (tc.startsWith('outbound.')) {
    return 'border-amber-400/40 bg-amber-500/15 text-amber-700 dark:text-amber-300';
  }
  if (tc === 'stream.chunk') {
    return 'border-violet-400/40 bg-violet-500/10 text-violet-700 dark:text-violet-300';
  }
  return 'border-border/70 bg-muted text-muted-foreground';
}

/** Wider single-line preview for the logs message scope filter strip (full id on ``title``). */
export function msgIdFilterPreview(id: string, maxChars = 96): string {
  const t = id.trim();
  if (t.length <= maxChars) return t;
  return `${t.slice(0, Math.max(1, maxChars - 1))}…`;
}
