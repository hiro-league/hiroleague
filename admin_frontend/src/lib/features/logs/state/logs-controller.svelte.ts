import { tick } from 'svelte';
import { listDevices, type DeviceRow } from '$lib/api/channels-devices';
import {
  clearLogs,
  discoverLogMethods,
  getLogsLayout,
  logTimeRangeSeconds,
  searchLogs,
  tailLogs,
  type LogRow,
  type LogSourceFilter,
  type LogsLayout
} from '$lib/api/logs';
import { openWorkspaceFolder } from '$lib/api/server';
import type { Notify } from '$lib/features/server/types';
import type { LogsPreferences } from './logs-preferences.svelte';
import {
  logIdFromRowKey,
  rowPassesFilters,
  sourcesForLayout,
  withRenderKeys,
  type RenderLogRow
} from '../shared/logs-ui';

const INITIAL_TAIL_LINES = 500;

/** API + polling orchestration for the logs page (prefs own session-restored filter state). */
export function createLogsPageController(opts: { prefs: LogsPreferences }) {
  const { prefs } = opts;

  let layout = $state<LogsLayout | null>(null);
  let rows = $state<RenderLogRow[]>([]);
  let fileOffsets = $state<Record<string, number>>({});
  let loading = $state(true);
  let error = $state<string | null>(null);
  let pollError = $state<string | null>(null);
  let logMethods = $state<string[]>([]);
  let pairedDevices = $state<DeviceRow[]>([]);

  const devicesForLogs = $derived.by<DeviceRow[]>(() => {
    const seen = new Set<string>();
    for (const r of rows) {
      const id = (r.scope_device_id ?? '').trim();
      if (id) seen.add(id);
    }
    if (seen.size === 0) return [];
    const byId = new Map<string, DeviceRow>(pairedDevices.map((d) => [d.device_id, d]));
    const out: DeviceRow[] = [];
    for (const id of seen) {
      const paired = byId.get(id);
      if (paired) {
        out.push(paired);
      } else {
        out.push({
          device_id: id,
          device_name: null,
          paired_at: '',
          expires_at: null
        });
      }
    }
    out.sort((a, b) =>
      (a.device_name?.trim() || a.device_id).localeCompare(b.device_name?.trim() || b.device_id)
    );
    return out;
  });
  let searchBusy = $state(false);
  let clearingLogs = $state(false);
  let initialized = $state(false);
  let activeRowKey = $state<string | null>(null);

  let polling = false;
  let searchTimer: number | null = null;
  let searchFetchGeneration = 0;

  /** Per page visit: stable 1,2,3… per distinct ``scope_msg_id`` (survives row filters; see sync effect). */
  const scopeMsgOrdinalMap = new Map<string, number>();
  let scopeMsgOrdinalSeq = 1;
  let scopeMsgOrdinalVersion = $state(0);

  const availableSources = $derived.by<LogSourceFilter[]>(() => sourcesForLayout(layout));

  const channelsVisible = $derived(prefs.activeSources.includes('channels'));

  const isSearchMode = $derived(prefs.searchText.trim().length > 0);

  const hasScopeFilters = $derived.by(() => {
    return (
      !!prefs.scopeDeviceId.trim() || !!prefs.scopeMsgId.trim() || !!prefs.scopeMethod.trim()
    );
  });

  const blocksLiveTail = $derived(isSearchMode || hasScopeFilters);

  const filterCtx = $derived({
    activeSources: prefs.activeSources,
    activeChannel: prefs.activeChannel,
    levelFilter: prefs.levelFilter,
    trafficClassFilter: prefs.trafficClassFilter
  });

  const visibleRows = $derived.by(() => {
    const ctx = filterCtx;
    const filtered = rows.filter((row) => rowPassesFilters(row, ctx));
    const direction = prefs.sortOrder === 'newest' ? -1 : 1;
    return [...filtered].sort((a, b) => (a.timestamp - b.timestamp) * direction);
  });

  const activeRow = $derived(
    activeRowKey ? visibleRows.find((row) => row._rowKey === activeRowKey) ?? null : null
  );

  /**
   * Chip color A/B alternates when the message ordinal changes between consecutive visible rows
   * (rows without a scope column are skipped so the stripe does not flip on blank lines).
   */
  const scopeMsgChipStripeByRowKey = $derived.by(() => {
    void scopeMsgOrdinalVersion;
    const out = new Map<string, boolean>();
    let alt = false;
    let lastOrd: number | null = null;
    for (const row of visibleRows) {
      const id = row.scope_msg_id?.trim();
      if (!id) continue;
      const ord = scopeMsgOrdinalMap.get(id) ?? null;
      if (ord == null) continue;
      if (lastOrd !== null && ord !== lastOrd) alt = !alt;
      lastOrd = ord;
      out.set(row._rowKey, alt);
    }
    return out;
  });

  /** Assign next ordinal on first chronological sighting of each ``scope_msg_id`` in loaded rows. */
  function syncScopeMsgOrdinalsFromRows(allRows: RenderLogRow[]) {
    if (allRows.length === 0) return;
    const sorted = [...allRows].sort((a, b) => a.timestamp - b.timestamp);
    let added = false;
    for (const row of sorted) {
      const id = row.scope_msg_id?.trim();
      if (!id) continue;
      if (!scopeMsgOrdinalMap.has(id)) {
        scopeMsgOrdinalMap.set(id, scopeMsgOrdinalSeq++);
        added = true;
      }
    }
    if (added) scopeMsgOrdinalVersion++;
  }

  $effect(() => {
    rows;
    syncScopeMsgOrdinalsFromRows(rows);
  });

  $effect(() => {
    if (!prefs.detailPanelOpen || activeRow !== null || visibleRows.length === 0) return;
    activeRowKey = visibleRows[0]!._rowKey;
  });

  function setActiveRow(row: RenderLogRow | null) {
    activeRowKey = row?._rowKey ?? null;
  }

  function toggleDetailPanel() {
    prefs.detailPanelOpen = !prefs.detailPanelOpen;
    if (prefs.detailPanelOpen && activeRow === null && visibleRows.length > 0) {
      activeRowKey = visibleRows[0]!._rowKey;
    }
  }

  async function afterScopeChange() {
    loading = true;
    error = null;
    try {
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reload logs.';
    } finally {
      loading = false;
    }
  }

  function removeScopeDevice() {
    prefs.scopeDeviceId = '';
    void afterScopeChange();
  }

  function removeScopeMsg() {
    prefs.scopeMsgId = '';
    void afterScopeChange();
  }

  function removeScopeMethod() {
    prefs.scopeMethod = '';
    void afterScopeChange();
  }

  function clearTrafficClassFilter() {
    prefs.trafficClassFilter = [];
  }

  function filterToMessage(msgId: string, event: MouseEvent) {
    event.stopPropagation();
    prefs.scopeMsgId = msgId;
    void afterScopeChange();
  }

  async function initialize() {
    loading = true;
    error = null;
    try {
      const layoutPayload = await getLogsLayout();
      const nextLayout = layoutPayload.data;
      layout = nextLayout;
      const validSources = sourcesForLayout(nextLayout);
      const restoredSources = prefs.activeSources.filter((source) => validSources.includes(source));
      prefs.activeSources =
        prefs.activeSources.length > 0 && restoredSources.length > 0 ? restoredSources : validSources;
      prefs.activeChannel = nextLayout.available_channels.includes(prefs.activeChannel)
        ? prefs.activeChannel
        : '';
      try {
        const [methodsPayload, devicesPayload] = await Promise.all([
          discoverLogMethods(),
          listDevices()
        ]);
        logMethods = methodsPayload.data ?? [];
        pairedDevices = devicesPayload.data ?? [];
      } catch {
        logMethods = [];
        pairedDevices = [];
      }
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load logs.';
      rows = [];
    } finally {
      loading = false;
      initialized = true;
    }
  }

  function buildTailRequestBody(
    afterOffsets?: Record<string, number> | null
  ): Parameters<typeof tailLogs>[0] {
    if (afterOffsets && Object.keys(afterOffsets).length > 0) {
      return { after_offsets: afterOffsets };
    }
    const body: Parameters<typeof tailLogs>[0] = {
      lines: INITIAL_TAIL_LINES,
      last_session_only: prefs.lastSessionOnly
    };
    if (!prefs.lastSessionOnly) {
      const sec = logTimeRangeSeconds(prefs.logTimeRange);
      if (sec !== null) {
        body.since_seconds_ago = sec;
      }
    }
    return body;
  }

  function trimRowsToRollingWindow() {
    if (prefs.lastSessionOnly) return;
    const sec = logTimeRangeSeconds(prefs.logTimeRange);
    if (sec === null) return;
    const cutoff = Date.now() / 1000 - sec;
    rows = rows.filter((r) => r.timestamp >= cutoff);
  }

  /** After a full tail reload, reattach selection when the same log line is still shown (same API ``id`` + filters). */
  function reconcileActiveRowAfterTailReload(
    prevRowKey: string | null,
    nextRows: RenderLogRow[]
  ): void {
    const ctx = filterCtx;
    if (prevRowKey) {
      const logId = logIdFromRowKey(prevRowKey);
      const row = nextRows.find((r) => r.id === logId && rowPassesFilters(r, ctx));
      activeRowKey = row ? row._rowKey : null;
      return;
    }
    if (nextRows.length > 0 && !activeRowKey) {
      const visible = nextRows.filter((r) => rowPassesFilters(r, ctx));
      if (visible.length > 0) activeRowKey = visible[0]!._rowKey;
    }
  }

  async function reloadRows() {
    fileOffsets = {};
    const trimmed = prefs.searchText.trim();
    const scopeActive =
      !!prefs.scopeDeviceId.trim() || !!prefs.scopeMsgId.trim() || !!prefs.scopeMethod.trim();
    if (trimmed || scopeActive) {
      await fetchFilteredRows(trimmed);
      return;
    }
    const prevRowKey = activeRowKey;
    const payload = await tailLogs(buildTailRequestBody());
    rows = withRenderKeys(payload.data.rows);
    fileOffsets = payload.data.file_offsets;
    reconcileActiveRowAfterTailReload(prevRowKey, rows);
  }

  async function fetchFilteredRows(expectedSearch?: string) {
    const trimmed = (expectedSearch ?? prefs.searchText).trim();
    const myGen = ++searchFetchGeneration;
    searchBusy = true;
    error = null;
    try {
      const payload = await searchLogs({
        query: trimmed || undefined,
        deviceId: prefs.scopeDeviceId.trim() || undefined,
        msgId: prefs.scopeMsgId.trim() || undefined,
        method: prefs.scopeMethod.trim() || undefined,
        trafficClasses:
          prefs.trafficClassFilter.length > 0 ? [...prefs.trafficClassFilter] : undefined
      });
      if (myGen !== searchFetchGeneration) return;
      rows = withRenderKeys(payload.data.rows);
      fileOffsets = {};
      activeRowKey = rows[0]?._rowKey ?? null;
    } catch (err) {
      if (myGen !== searchFetchGeneration) return;
      error = err instanceof Error ? err.message : 'Search failed.';
      rows = [];
      activeRowKey = null;
    } finally {
      if (myGen === searchFetchGeneration) {
        searchBusy = false;
      }
    }
  }

  async function poll() {
    const tailBlocked =
      prefs.searchText.trim().length > 0 ||
      !!prefs.scopeDeviceId.trim() ||
      !!prefs.scopeMsgId.trim() ||
      !!prefs.scopeMethod.trim();
    if (prefs.paused || tailBlocked || loading || polling || Object.keys(fileOffsets).length === 0) {
      return;
    }
    polling = true;
    try {
      const payload = await tailLogs(buildTailRequestBody(fileOffsets));
      pollError = null;
      fileOffsets = payload.data.file_offsets;
      if (payload.data.rows.length > 0) {
        rows = [...rows, ...withRenderKeys(payload.data.rows, rows.length)];
      }
      trimRowsToRollingWindow();
    } catch (err) {
      pollError = err instanceof Error ? err.message : 'Live log polling failed.';
    } finally {
      polling = false;
    }
  }

  async function runSearchFromInput() {
    const trimmed = prefs.searchText.trim();
    const scopeActive =
      !!prefs.scopeDeviceId.trim() || !!prefs.scopeMsgId.trim() || !!prefs.scopeMethod.trim();
    if (!trimmed && !scopeActive) {
      if (searchTimer) {
        window.clearTimeout(searchTimer);
        searchTimer = null;
      }
      loading = true;
      try {
        await reloadRows();
      } catch (err) {
        error = err instanceof Error ? err.message : 'Failed to reload logs.';
      } finally {
        loading = false;
      }
      return;
    }
    await fetchFilteredRows();
  }

  function onSearchInput(event: Event) {
    prefs.searchText = (event.currentTarget as HTMLInputElement).value;
    if (searchTimer) {
      window.clearTimeout(searchTimer);
    }
    searchTimer = window.setTimeout(() => {
      searchTimer = null;
      void runSearchFromInput();
    }, 250);
  }

  async function clearSearch() {
    prefs.searchText = '';
    if (searchTimer) {
      window.clearTimeout(searchTimer);
      searchTimer = null;
    }
    loading = true;
    try {
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reload logs.';
    } finally {
      loading = false;
    }
  }

  async function clearAllFilters() {
    prefs.searchText = '';
    prefs.scopeDeviceId = '';
    prefs.scopeMsgId = '';
    prefs.scopeMethod = '';
    prefs.trafficClassFilter = [];
    if (searchTimer) {
      window.clearTimeout(searchTimer);
      searchTimer = null;
    }
    searchFetchGeneration += 1;
    loading = true;
    error = null;
    try {
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reload logs.';
    } finally {
      loading = false;
    }
  }

  async function clearAllLogs() {
    clearingLogs = true;
    loading = true;
    error = null;
    pollError = null;
    searchFetchGeneration += 1;
    try {
      await clearLogs();
      rows = [];
      fileOffsets = {};
      activeRowKey = null;
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to clear logs.';
    } finally {
      loading = false;
      clearingLogs = false;
    }
  }

  function moveActiveRow(delta: number, getScroller: () => HTMLElement | null) {
    if (visibleRows.length === 0) return;
    const currentIndex = activeRowKey
      ? visibleRows.findIndex((row) => row._rowKey === activeRowKey)
      : -1;
    const nextIndex =
      currentIndex < 0
        ? 0
        : Math.min(Math.max(currentIndex + delta, 0), visibleRows.length - 1);
    setActiveRow(visibleRows[nextIndex]!);
    void tick().then(() => {
      getScroller()
        ?.querySelector('tr[data-active="true"]')
        ?.scrollIntoView({ block: 'nearest' });
    });
  }

  function handleTableKeydown(event: KeyboardEvent, getScroller: () => HTMLElement | null) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveActiveRow(1, getScroller);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveActiveRow(-1, getScroller);
    }
  }

  async function reloadLiveTail() {
    if (blocksLiveTail) return;
    loading = true;
    error = null;
    try {
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reload logs.';
    } finally {
      loading = false;
    }
  }

  function dispose() {
    if (searchTimer) {
      window.clearTimeout(searchTimer);
      searchTimer = null;
    }
    scopeMsgOrdinalMap.clear();
    scopeMsgOrdinalSeq = 1;
    scopeMsgOrdinalVersion++;
  }

  function getScopeMsgOrdinal(msgId: string | null | undefined): number | null {
    scopeMsgOrdinalVersion;
    const id = msgId?.trim();
    if (!id) return null;
    return scopeMsgOrdinalMap.get(id) ?? null;
  }

  function getScopeMsgChipStripeAlt(rowKey: string): boolean {
    return scopeMsgChipStripeByRowKey.get(rowKey) ?? false;
  }

  /** Opens the resolved workspace log directory in the OS file manager (same API as workspaces tab). */
  async function openLogsFolder(notify: Notify) {
    const dir = layout?.log_dir?.trim();
    if (!dir) {
      notify('error', 'Log folder path is not available yet.');
      return;
    }
    try {
      await openWorkspaceFolder(dir);
      notify('info', `Opening folder: ${dir}`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Open folder failed.');
    }
  }

  return {
    get layout() {
      return layout;
    },
    get rows() {
      return rows;
    },
    get fileOffsets() {
      return fileOffsets;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    get pollError() {
      return pollError;
    },
    get logMethods() {
      return logMethods;
    },
    get devicesForLogs() {
      return devicesForLogs;
    },
    get searchBusy() {
      return searchBusy;
    },
    get clearingLogs() {
      return clearingLogs;
    },
    get initialized() {
      return initialized;
    },
    get activeRowKey() {
      return activeRowKey;
    },
    set activeRowKey(v: string | null) {
      activeRowKey = v;
    },
    // Getters: object literal shorthand for $derived would freeze initial values (state_referenced_locally).
    get availableSources() {
      return availableSources;
    },
    get channelsVisible() {
      return channelsVisible;
    },
    get isSearchMode() {
      return isSearchMode;
    },
    get hasScopeFilters() {
      return hasScopeFilters;
    },
    get blocksLiveTail() {
      return blocksLiveTail;
    },
    get visibleRows() {
      return visibleRows;
    },
    get activeRow() {
      return activeRow;
    },
    initialize,
    reloadRows,
    poll,
    onSearchInput,
    clearSearch,
    clearAllFilters,
    clearAllLogs,
    afterScopeChange,
    removeScopeDevice,
    removeScopeMsg,
    removeScopeMethod,
    clearTrafficClassFilter,
    filterToMessage,
    setActiveRow,
    toggleDetailPanel,
    moveActiveRow,
    handleTableKeydown,
    reloadLiveTail,
    dispose,
    openLogsFolder,
    getScopeMsgOrdinal,
    getScopeMsgChipStripeAlt
  };
}

export type LogsPageController = ReturnType<typeof createLogsPageController>;
