import {
  isTrafficClass,
  LOG_LEVELS,
  LOG_TIME_RANGES,
  TRAFFIC_CLASSES,
  type LogLevel,
  type LogSourceFilter,
  type LogTimeRange,
  type TrafficClass
} from '$lib/api/logs';
import {
  isLogLevel,
  isLogSourceFilter,
  LOGS_PREF_SESSION_KEY,
  type LogSortColumn,
  type LogSortDir
} from '$lib/features/logs/shared/logs-ui';
import {
  jsonArrayField,
  jsonBoolField,
  jsonEnumField,
  jsonRecordCodec,
  jsonStringField,
  type FieldSchema
} from '$lib/state/codecs';
import { createPersistentRecord } from '$lib/state/create-persistent-state.svelte';

/** Session-backed logs UI preferences — all fields required (defaults fill gaps on decode). */
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

const LOGS_PREFS_DEFAULTS: LogsPrefs = {
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

const logsPrefsSchema: FieldSchema<LogsPrefs> = {
  paused: jsonBoolField(LOGS_PREFS_DEFAULTS.paused),
  sortColumn: jsonEnumField<LogSortColumn>(
    ['time', 'level', 'source', 'module', 'class', 'subclass', 'message'],
    LOGS_PREFS_DEFAULTS.sortColumn
  ),
  sortDir: jsonEnumField<LogSortDir>(['asc', 'desc'], LOGS_PREFS_DEFAULTS.sortDir),
  activeSources: jsonArrayField(
    (item): item is LogSourceFilter => typeof item === 'string' && isLogSourceFilter(item),
    LOGS_PREFS_DEFAULTS.activeSources
  ),
  activeChannel: {
    decode(raw) {
      if (typeof raw === 'string') return raw;
      if (Array.isArray(raw) && raw[0]) return String(raw[0]);
      return LOGS_PREFS_DEFAULTS.activeChannel;
    },
    encode: (v) => v
  },
  levelFilter: jsonArrayField(
    (item): item is LogLevel => typeof item === 'string' && isLogLevel(item),
    LOGS_PREFS_DEFAULTS.levelFilter
  ),
  searchText: jsonStringField(''),
  scopeDeviceId: jsonStringField(''),
  scopeMsgId: jsonStringField(''),
  scopeMethod: jsonStringField(''),
  trafficClassFilter: jsonArrayField(
    (item): item is TrafficClass => typeof item === 'string' && isTrafficClass(item),
    LOGS_PREFS_DEFAULTS.trafficClassFilter
  ),
  detailPanelOpen: jsonBoolField(LOGS_PREFS_DEFAULTS.detailPanelOpen),
  controlsCollapsed: jsonBoolField(LOGS_PREFS_DEFAULTS.controlsCollapsed),
  lastSessionOnly: jsonBoolField(LOGS_PREFS_DEFAULTS.lastSessionOnly),
  logTimeRange: jsonEnumField<LogTimeRange>(LOG_TIME_RANGES, LOGS_PREFS_DEFAULTS.logTimeRange)
};

const logsPrefsCodec = jsonRecordCodec(logsPrefsSchema, LOGS_PREFS_DEFAULTS);

/** Session-backed logs UI preferences (filters, layout toggles). */
export function createLogsPreferences() {
  const prefs = createPersistentRecord({
    key: LOGS_PREF_SESSION_KEY,
    tier: 'session',
    codec: logsPrefsCodec,
    defaults: LOGS_PREFS_DEFAULTS
  });

  function sourceIsActive(source: LogSourceFilter) {
    return prefs.activeSources.includes(source);
  }

  function levelIsActive(level: LogLevel) {
    return prefs.levelFilter.includes(level);
  }

  function toggleSource(source: LogSourceFilter) {
    prefs.activeSources = sourceIsActive(source)
      ? prefs.activeSources.filter((item) => item !== source)
      : [...prefs.activeSources, source];
  }

  function toggleLevel(level: LogLevel) {
    prefs.levelFilter = levelIsActive(level)
      ? prefs.levelFilter.filter((item) => item !== level)
      : [...prefs.levelFilter, level];
  }

  function trafficClassIsActive(tc: TrafficClass) {
    return prefs.trafficClassFilter.includes(tc);
  }

  function toggleTrafficClass(tc: TrafficClass) {
    prefs.trafficClassFilter = trafficClassIsActive(tc)
      ? prefs.trafficClassFilter.filter((item) => item !== tc)
      : [...prefs.trafficClassFilter, tc];
  }

  /** Click a column header: same column flips direction, new column starts at a
   * sensible default (time descending = newest first, text columns ascending). */
  function toggleSortColumn(col: LogSortColumn) {
    if (prefs.sortColumn === col) {
      prefs.sortDir = prefs.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      prefs.sortColumn = col;
      prefs.sortDir = col === 'time' ? 'desc' : 'asc';
    }
  }

  function togglePause() {
    prefs.paused = !prefs.paused;
  }

  function toggleControlsCollapsed() {
    prefs.controlsCollapsed = !prefs.controlsCollapsed;
  }

  return Object.assign(prefs, {
    sourceIsActive,
    levelIsActive,
    trafficClassIsActive,
    toggleSource,
    toggleLevel,
    toggleTrafficClass,
    toggleSortColumn,
    togglePause,
    toggleControlsCollapsed
  });
}

export type LogsPreferences = ReturnType<typeof createLogsPreferences>;
