import { describe, expect, it } from 'vitest';

import { LOG_LEVELS, TRAFFIC_CLASSES } from '$lib/api/logs';
import { jsonRecordCodec } from '$lib/state/codecs';
import {
  jsonArrayField,
  jsonBoolField,
  jsonEnumField,
  jsonStringField,
  type FieldSchema
} from '$lib/state/codecs';
import {
  isLogLevel,
  isLogSourceFilter,
  type LogSortColumn,
  type LogSortDir
} from '$lib/features/logs/shared/logs-ui';
import { isTrafficClass, LOG_TIME_RANGES, type LogLevel, type LogSourceFilter, type LogTimeRange, type TrafficClass } from '$lib/api/logs';

type LogsPrefs = {
  paused: boolean;
  sortColumn: LogSortColumn;
  sortDir: LogSortDir;
  activeSources: LogSourceFilter[];
  activeChannel: string;
  levelFilter: LogLevel[];
  searchText: string;
  scopeDeviceId: string;
  scopeMsgId: string;
  scopeMethod: string;
  trafficClassFilter: TrafficClass[];
  detailPanelOpen: boolean;
  controlsCollapsed: boolean;
  lastSessionOnly: boolean;
  logTimeRange: LogTimeRange;
};

const defaults: LogsPrefs = {
  paused: false,
  sortColumn: 'time',
  sortDir: 'desc',
  activeSources: [],
  activeChannel: '',
  levelFilter: [...LOG_LEVELS],
  searchText: '',
  scopeDeviceId: '',
  scopeMsgId: '',
  scopeMethod: '',
  trafficClassFilter: [...TRAFFIC_CLASSES],
  detailPanelOpen: false,
  controlsCollapsed: false,
  lastSessionOnly: true,
  logTimeRange: '1h'
};

const schema: FieldSchema<LogsPrefs> = {
  paused: jsonBoolField(defaults.paused),
  sortColumn: jsonEnumField<LogSortColumn>(
    ['time', 'level', 'source', 'module', 'class', 'subclass', 'message'],
    defaults.sortColumn
  ),
  sortDir: jsonEnumField<LogSortDir>(['asc', 'desc'], defaults.sortDir),
  activeSources: jsonArrayField(
    (item): item is LogSourceFilter => typeof item === 'string' && isLogSourceFilter(item),
    defaults.activeSources
  ),
  activeChannel: {
    decode(raw) {
      if (typeof raw === 'string') return raw;
      if (Array.isArray(raw) && raw[0]) return String(raw[0]);
      return defaults.activeChannel;
    },
    encode: (v) => v
  },
  levelFilter: jsonArrayField(
    (item): item is LogLevel => typeof item === 'string' && isLogLevel(item),
    defaults.levelFilter
  ),
  searchText: jsonStringField(''),
  scopeDeviceId: jsonStringField(''),
  scopeMsgId: jsonStringField(''),
  scopeMethod: jsonStringField(''),
  trafficClassFilter: jsonArrayField(
    (item): item is TrafficClass => typeof item === 'string' && isTrafficClass(item),
    defaults.trafficClassFilter
  ),
  detailPanelOpen: jsonBoolField(defaults.detailPanelOpen),
  controlsCollapsed: jsonBoolField(defaults.controlsCollapsed),
  lastSessionOnly: jsonBoolField(defaults.lastSessionOnly),
  logTimeRange: jsonEnumField<LogTimeRange>(LOG_TIME_RANGES, defaults.logTimeRange)
};

const codec = jsonRecordCodec(schema, defaults);

describe('logs prefs codec', () => {
  it('matches the legacy sessionStorage JSON shape', () => {
    const legacy = JSON.stringify({
      paused: true,
      sortColumn: 'level',
      sortDir: 'asc',
      activeSources: ['server'],
      activeChannel: 'devices',
      levelFilter: ['ERROR'],
      searchText: 'timeout',
      scopeDeviceId: 'dev-1',
      scopeMsgId: 'msg-9',
      scopeMethod: 'ping',
      trafficClassFilter: ['inbound.message'],
      detailPanelOpen: true,
      controlsCollapsed: true,
      lastSessionOnly: false,
      logTimeRange: '2h'
    });
    expect(codec.decode(legacy)).toEqual({
      paused: true,
      sortColumn: 'level',
      sortDir: 'asc',
      activeSources: ['server'],
      activeChannel: 'devices',
      levelFilter: ['ERROR'],
      searchText: 'timeout',
      scopeDeviceId: 'dev-1',
      scopeMsgId: 'msg-9',
      scopeMethod: 'ping',
      trafficClassFilter: ['inbound.message'],
      detailPanelOpen: true,
      controlsCollapsed: true,
      lastSessionOnly: false,
      logTimeRange: '2h'
    });
    expect(codec.encode(codec.decode(legacy))).toBe(legacy);
  });

  it('keeps valid fields when one field is corrupt', () => {
    const raw = JSON.stringify({ sortColumn: 'time', sortDir: 'not-a-dir', searchText: 'ok' });
    expect(codec.decode(raw)).toMatchObject({ sortColumn: 'time', sortDir: 'desc', searchText: 'ok' });
  });
});
