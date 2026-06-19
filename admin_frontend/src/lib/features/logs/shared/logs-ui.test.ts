import { describe, expect, it } from 'vitest';
import type { LogLevel, LogRow, TrafficClass } from '$lib/api/logs';
import { compareLogRows, rowPassesFilters, type RowFilterContext } from './logs-ui';

function row(p: Partial<LogRow> & Pick<LogRow, 'id' | 'timestamp'>): LogRow {
  return {
    timestamp_display: '',
    date_display: '',
    source: 'server',
    level: 'INFO',
    level_html: '',
    module: '',
    module_html: '',
    message: '',
    message_html: '',
    message_pretty: null,
    extra: '',
    extra_html: '',
    extra_tooltip_html: '',
    extra_segments: [],
    is_startup: false,
    ...p
  };
}

const allSourcesCtx = (): RowFilterContext => ({
  activeSources: ['server', 'channels', 'gateway', 'cli'],
  activeChannel: '',
  levelFilter: [],
  trafficClassFilter: [
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
  ]
});

describe('compareLogRows', () => {
  it('sorts by timestamp ascending for the time column', () => {
    const a = row({ id: 'a', timestamp: 100 });
    const b = row({ id: 'b', timestamp: 200 });
    expect(compareLogRows(a, b, 'time')).toBeLessThan(0);
    expect(compareLogRows(b, a, 'time')).toBeGreaterThan(0);
  });

  it('orders log levels by LOG_LEVELS index', () => {
    const info = row({ id: 'i', timestamp: 1, level: 'INFO' });
    const err = row({ id: 'e', timestamp: 1, level: 'ERROR' });
    expect(compareLogRows(info, err, 'level')).toBeLessThan(0);
  });

  it('uses timestamp as a stable tiebreak when primary keys match', () => {
    const older = row({ id: 'a', timestamp: 10, message: 'same' });
    const newer = row({ id: 'b', timestamp: 20, message: 'same' });
    expect(compareLogRows(older, newer, 'message')).toBeLessThan(0);
  });

  it('compares source labels (channel rows include channel id)', () => {
    const srv = row({ id: 's', timestamp: 1, source: 'server' });
    const ch = row({ id: 'c', timestamp: 1, source: 'channel-general' });
    expect(compareLogRows(srv, ch, 'source')).not.toBe(0);
  });
});

describe('rowPassesFilters', () => {
  it('hides server rows when server source is deselected', () => {
    const ctx = { ...allSourcesCtx(), activeSources: ['channels'] as RowFilterContext['activeSources'] };
    expect(rowPassesFilters(row({ id: '1', timestamp: 1, source: 'server' }), ctx)).toBe(false);
    expect(rowPassesFilters(row({ id: '2', timestamp: 1, source: 'channel-a' }), ctx)).toBe(true);
  });

  it('filters channel rows by activeChannel when set', () => {
    const ctx = { ...allSourcesCtx(), activeChannel: 'general' };
    expect(rowPassesFilters(row({ id: '1', timestamp: 1, source: 'channel-general' }), ctx)).toBe(
      true
    );
    expect(rowPassesFilters(row({ id: '2', timestamp: 1, source: 'channel-other' }), ctx)).toBe(
      false
    );
  });

  it('applies level filter when non-empty', () => {
    const ctx = { ...allSourcesCtx(), levelFilter: ['ERROR'] as LogLevel[] };
    expect(rowPassesFilters(row({ id: '1', timestamp: 1, level: 'ERROR' }), ctx)).toBe(true);
    expect(rowPassesFilters(row({ id: '2', timestamp: 1, level: 'INFO' }), ctx)).toBe(false);
  });

  it('hides classed rows when their traffic class is not selected', () => {
    const ctx = { ...allSourcesCtx(), trafficClassFilter: ['inbound.message'] as TrafficClass[] };
    expect(
      rowPassesFilters(
        row({ id: '1', timestamp: 1, scope_traffic_class: 'inbound.message' }),
        ctx
      )
    ).toBe(true);
    expect(
      rowPassesFilters(
        row({ id: '2', timestamp: 1, scope_traffic_class: 'outbound.reply' }),
        ctx
      )
    ).toBe(false);
  });

  it('never hides rows without a traffic class via the traffic facet', () => {
    const ctx = { ...allSourcesCtx(), trafficClassFilter: [] as TrafficClass[] };
    expect(rowPassesFilters(row({ id: '1', timestamp: 1 }), ctx)).toBe(true);
    expect(
      rowPassesFilters(row({ id: '2', timestamp: 1, scope_traffic_class: 'inbound.message' }), ctx)
    ).toBe(false);
  });
});
