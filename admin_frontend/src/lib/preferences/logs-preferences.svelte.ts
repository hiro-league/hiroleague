import {
  isTrafficClass,
  LOG_LEVELS,
  TRAFFIC_CLASSES,
  type LogLevel,
  type LogSourceFilter,
  type LogTimeRange,
  type TrafficClass
} from '$lib/api/logs';
import {
  isLogLevel,
  isLogSortColumn,
  isLogSourceFilter,
  isLogTimeRange,
  LOGS_PREF_SESSION_KEY,
  type LogSortColumn,
  type LogSortDir,
  type LogsPrefsSnapshot
} from '$lib/features/logs/shared/logs-ui';

/** Session-backed logs UI preferences (filters, layout toggles). */
export function createLogsPreferences() {
  let paused = $state(false);
  // Table column sort (replaces the old newest/oldest toggle). Default newest-first.
  let sortColumn = $state<LogSortColumn>('time');
  let sortDir = $state<LogSortDir>('desc');
  let activeSources = $state<LogSourceFilter[]>([]);
  let activeChannel = $state('');
  let levelFilter = $state<LogLevel[]>([...LOG_LEVELS]);
  let searchText = $state('');
  let scopeDeviceId = $state('');
  let scopeMsgId = $state('');
  let scopeMethod = $state('');
  // Traffic facet defaults to all classes selected (= show everything); clearing
  // hides classed rows. See rowPassesFilters.
  let trafficClassFilter = $state<TrafficClass[]>([...TRAFFIC_CLASSES]);
  let detailPanelOpen = $state(false);
  let controlsCollapsed = $state(false);
  /** When true, initial tail starts at latest Hiro Server startup line (time range ignored on server). */
  let lastSessionOnly = $state(true);
  let logTimeRange = $state<LogTimeRange>('1h');

  function hydrateFromSession() {
    const raw = sessionStorage.getItem(LOGS_PREF_SESSION_KEY);
    if (!raw) return;
    try {
      const prefs = JSON.parse(raw) as LogsPrefsSnapshot;
      paused = Boolean(prefs.paused);
      sortColumn = isLogSortColumn(prefs.sortColumn) ? prefs.sortColumn : 'time';
      sortDir = prefs.sortDir === 'asc' ? 'asc' : 'desc';
      activeSources = (prefs.activeSources ?? []).filter(isLogSourceFilter);
      activeChannel =
        typeof prefs.activeChannel === 'string'
          ? prefs.activeChannel
          : Array.isArray(prefs.activeChannels)
            ? prefs.activeChannels[0] ?? ''
            : '';
      levelFilter = (prefs.levelFilter ?? [...LOG_LEVELS]).filter(isLogLevel);
      searchText = String(prefs.searchText ?? '');
      scopeDeviceId = String(prefs.scopeDeviceId ?? '');
      scopeMsgId = String(prefs.scopeMsgId ?? '');
      scopeMethod = String(prefs.scopeMethod ?? '');
      trafficClassFilter = Array.isArray(prefs.trafficClassFilter)
        ? prefs.trafficClassFilter.filter(isTrafficClass)
        : [...TRAFFIC_CLASSES];
      detailPanelOpen = Boolean(prefs.detailPanelOpen);
      controlsCollapsed = Boolean(prefs.controlsCollapsed);
      lastSessionOnly =
        typeof prefs.lastSessionOnly === 'boolean' ? prefs.lastSessionOnly : true;
      const tr = prefs.logTimeRange;
      logTimeRange = typeof tr === 'string' && isLogTimeRange(tr) ? tr : '1h';
    } catch {
      sessionStorage.removeItem(LOGS_PREF_SESSION_KEY);
    }
  }

  function persistToSession() {
    const snapshot: LogsPrefsSnapshot = {
      paused,
      sortColumn,
      sortDir,
      activeSources,
      activeChannel,
      levelFilter,
      searchText,
      scopeDeviceId,
      scopeMsgId,
      scopeMethod,
      trafficClassFilter,
      detailPanelOpen,
      controlsCollapsed,
      lastSessionOnly,
      logTimeRange
    };
    sessionStorage.setItem(LOGS_PREF_SESSION_KEY, JSON.stringify(snapshot));
  }

  function sourceIsActive(source: LogSourceFilter) {
    return activeSources.includes(source);
  }

  function levelIsActive(level: LogLevel) {
    return levelFilter.includes(level);
  }

  function toggleSource(source: LogSourceFilter) {
    activeSources = sourceIsActive(source)
      ? activeSources.filter((item) => item !== source)
      : [...activeSources, source];
  }

  function toggleLevel(level: LogLevel) {
    levelFilter = levelIsActive(level)
      ? levelFilter.filter((item) => item !== level)
      : [...levelFilter, level];
  }

  function trafficClassIsActive(tc: TrafficClass) {
    return trafficClassFilter.includes(tc);
  }

  function toggleTrafficClass(tc: TrafficClass) {
    trafficClassFilter = trafficClassIsActive(tc)
      ? trafficClassFilter.filter((item) => item !== tc)
      : [...trafficClassFilter, tc];
  }

  /** Click a column header: same column flips direction, new column starts at a
   * sensible default (time descending = newest first, text columns ascending). */
  function toggleSortColumn(col: LogSortColumn) {
    if (sortColumn === col) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortColumn = col;
      sortDir = col === 'time' ? 'desc' : 'asc';
    }
  }

  function togglePause() {
    paused = !paused;
  }

  function toggleControlsCollapsed() {
    controlsCollapsed = !controlsCollapsed;
  }

  return {
    get paused() {
      return paused;
    },
    set paused(v: boolean) {
      paused = v;
    },
    get sortColumn() {
      return sortColumn;
    },
    set sortColumn(v: LogSortColumn) {
      sortColumn = v;
    },
    get sortDir() {
      return sortDir;
    },
    set sortDir(v: LogSortDir) {
      sortDir = v;
    },
    get activeSources() {
      return activeSources;
    },
    set activeSources(v: LogSourceFilter[]) {
      activeSources = v;
    },
    get activeChannel() {
      return activeChannel;
    },
    set activeChannel(v: string) {
      activeChannel = v;
    },
    get levelFilter() {
      return levelFilter;
    },
    set levelFilter(v: LogLevel[]) {
      levelFilter = v;
    },
    get searchText() {
      return searchText;
    },
    set searchText(v: string) {
      searchText = v;
    },
    get scopeDeviceId() {
      return scopeDeviceId;
    },
    set scopeDeviceId(v: string) {
      scopeDeviceId = v;
    },
    get scopeMsgId() {
      return scopeMsgId;
    },
    set scopeMsgId(v: string) {
      scopeMsgId = v;
    },
    get scopeMethod() {
      return scopeMethod;
    },
    set scopeMethod(v: string) {
      scopeMethod = v;
    },
    get trafficClassFilter() {
      return trafficClassFilter;
    },
    set trafficClassFilter(v: TrafficClass[]) {
      trafficClassFilter = v;
    },
    get detailPanelOpen() {
      return detailPanelOpen;
    },
    set detailPanelOpen(v: boolean) {
      detailPanelOpen = v;
    },
    get controlsCollapsed() {
      return controlsCollapsed;
    },
    set controlsCollapsed(v: boolean) {
      controlsCollapsed = v;
    },
    get lastSessionOnly() {
      return lastSessionOnly;
    },
    set lastSessionOnly(v: boolean) {
      lastSessionOnly = v;
    },
    get logTimeRange() {
      return logTimeRange;
    },
    set logTimeRange(v: LogTimeRange) {
      logTimeRange = v;
    },
    hydrateFromSession,
    persistToSession,
    sourceIsActive,
    levelIsActive,
    trafficClassIsActive,
    toggleSource,
    toggleLevel,
    toggleTrafficClass,
    toggleSortColumn,
    togglePause,
    toggleControlsCollapsed
  };
}

export type LogsPreferences = ReturnType<typeof createLogsPreferences>;
