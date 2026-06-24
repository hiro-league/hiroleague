/**
 * Orchestration for the Graph Runs ledger UI: ledger tail polling, inspect tabs,
 * filters, dialogs.
 *
 * Graph runs now renders as the *second tab of the Logs page* (it no longer has
 * its own route). The host Logs page owns the primary `?tab=logs|runs` pill, so
 * this controller no longer tracks a primary tab — `activePane` is purely the
 * opened-run inspector state (`activeRunId ?? RUNS_TAB`). Memories moved to its
 * own page (`features/memories`); none of that state lives here anymore.
 *
 * Follows getters for `$derived` consumers (avoid returning shorthand `$derived`
 * from factory — stale capture).
 */
import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
import { getCharacter, listCharacters, type CharacterDetail, type CharacterRow } from '$lib/api/characters';
import { preserveStickyAnchorAround } from '$lib/components/page/table/preserve-sticky-anchor';
import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
import { distinctOptionsWithSentinel } from '$lib/components/page/table/distinct-options';
import {
  getGraphRun,
  getGraphRunLangsmithUrl,
  GRAPH_RUN_HEADER_FIELDS,
  GRAPH_RUN_HEADER_TAB_FIELDS,
  GRAPH_RUN_NODE_TABLE_FIELDS,
  type GraphLedgerRow
} from '$lib/api/graph-runs';
import { createPoller } from '$lib/state/create-poller.svelte';
import {
  formatAgentElapsedMs,
  formatUsdCostDisplay
} from '$lib/features/chat-channels/messages/agent-message-meta';
import { createGraphRunsPreferences } from '$lib/preferences/graph-runs-preferences.svelte';
import {
  RUN_ID_FIRST_CARD_CHARS,
  RUNS_TAB,
  trimRunIdForList,
  isKnowledgeStandaloneRun,
  isGraphIngestRun,
  graphRunKindLabel,
  filterGraphRunsRows,
  GRAPH_RUNS_FILTER_KEYS,
  type ActivePane,
  type GraphRunKindFilter,
} from '../graph-runs-pure';
import { graphRunsFetchInitialLedger, graphRunsLoadMoreLedger, graphRunsPollLedgerTail } from './graph-runs-ledger-service';
import { createGraphRunTraceModel } from './graph-runs-trace-model.svelte';
import { createRetrievalTraceDialogController } from './retrieval-trace-dialog.svelte';
import { getEvalRowByRunId } from '$lib/api/eval';
import { rowFromPayload, type EvalRow } from '$lib/features/eval/shared/eval-row';
import type { ToastKind } from '$lib/ui/toast-types';

const NOOP_NOTIFY = (_kind: ToastKind, _message: string): void => {};

export function createGraphRunsPageController(
  notify: (kind: ToastKind, message: string) => void = NOOP_NOTIFY
) {
  const uiPrefs = createGraphRunsPreferences();
  let rows = $state<GraphLedgerRow[]>([]);
  let openRunIds = $state<string[]>([]);
  /** Active opened-run inspector id (null → the ledger list). */
  let activeRunId = $state<string | null>(null);
  const activePane = $derived<ActivePane>(activeRunId ?? RUNS_TAB);

  // Retrieval + ingest trace caches / open-dialog state live in their own sub-model,
  // reactive against the active pane so its derivations recompute on run switch.
  const traces = createGraphRunTraceModel({ getActivePane: () => activePane });

  // --- Eval-detail bridge: open the rich eval row dialog from a `memory_recall` node ----------
  // The node carries the per-question run_id; we resolve it to the saved eval row and reuse the
  // Eval panel's detail dialog in place. `rowTraces` drives the (stacked) per-search trace dialog
  // its Trajectory tab opens — the same controller the Eval panel uses.
  const rowTraces = createRetrievalTraceDialogController(notify);
  let activeEvalRow = $state<EvalRow | null>(null);
  let evalRowLoadingRunId = $state<string | null>(null);
  const evalRowLegColumns = $derived(activeEvalRow ? Object.keys(activeEvalRow.legs) : []);

  async function openEvalRowForNode(row: GraphLedgerRow) {
    const runId = String(row.run_id ?? '').trim();
    if (!runId) return;
    evalRowLoadingRunId = runId;
    try {
      const res = await getEvalRowByRunId(runId);
      if (res.ok && res.data?.row) {
        activeEvalRow = rowFromPayload(res.data.row);
      } else {
        notify(
          'error',
          'No saved eval row found for this recall node (results may have been cleared).'
        );
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load the eval row.');
    } finally {
      evalRowLoadingRunId = null;
    }
  }

  function closeEvalRow() {
    activeEvalRow = null;
    rowTraces.closeTrace();
  }

  let timelineByRun = $state<Record<string, GraphLedgerRow[]>>({});
  let langsmithUrlByRun = $state<Record<string, string | undefined>>({});
  let aggregateByRun = $state<Record<string, GraphLedgerRow | null>>({});
  let chatChannels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);
  let titleCharacter = $state<CharacterDetail | null>(null);

  let error = $state('');

  let offsets: Record<string, number> = {};
  const runsPoller = createPoller(() => poll(), { intervalMs: 2500, pauseWhenHidden: true });
  let hasMoreRuns = $state(false);
  let historySkipFromEnd = $state(0);
  let loadingMoreRuns = $state(false);

  let selectedNodeRowId = $state<string | null>(null);
  let nodeDetailRowId = $state<string | null>(null);

  const tableFilters = useTableFilters({
    keys: GRAPH_RUNS_FILTER_KEYS,
    urlSync: true
  });

  function setGraphRunsFilter(key: (typeof GRAPH_RUNS_FILTER_KEYS)[number], value: string) {
    tableFilters.set(key, value);
    preserveStickyAnchorAround();
  }

  const characterMap = $derived.by((): Record<string, CharacterRow> => {
    const m: Record<string, CharacterRow> = {};
    for (const c of characters) m[c.id] = c;
    return m;
  });

  const channelById = $derived.by((): Map<number, ChatChannelRow> => {
    const m = new Map<number, ChatChannelRow>();
    for (const c of chatChannels) m.set(c.id, c);
    return m;
  });

  const charactersForFilterDropdown = $derived.by(() =>
    [...characters].sort((a, b) => a.name.localeCompare(b.name))
  );

  const channelsForFilterDropdown = $derived.by(() => {
    const cid = tableFilters.filters.gr_char.trim();
    const base = cid ? chatChannels.filter((c) => c.character_id === cid) : [...chatChannels];
    return base.sort((a, b) => a.name.localeCompare(b.name));
  });

  const statusesForFilterDropdown = $derived.by(() =>
    distinctOptionsWithSentinel(rows, (r) => String(r.status ?? ''), { emptyLabel: '(no status)' })
  );

  const visibleRows = $derived.by(() => filterGraphRunsRows(rows, tableFilters.filters));

  const timeline = $derived(activePane === RUNS_TAB ? [] : (timelineByRun[activePane] ?? []));

  const activeRunAggregate = $derived.by(() => {
    if (activePane === RUNS_TAB) return null;
    const rid = activePane;
    const fromInspect = aggregateByRun[rid];
    if (fromInspect) return fromInspect;
    return rows.find((row) => row.run_id === rid && String(row.row_kind) === 'run') ?? null;
  });

  const langsmithUrlForActive = $derived(
    activePane === RUNS_TAB ? null : (langsmithUrlByRun[activePane] ?? null)
  );

  const runIdentitySource = $derived.by((): GraphLedgerRow | null => {
    if (activePane === RUNS_TAB) return null;
    const agg = activeRunAggregate;
    if (agg) return agg;
    const tl = timelineByRun[activePane] ?? [];
    return tl[0] ?? null;
  });

  const activeChannelLabel = $derived.by(() => {
    const row = runIdentitySource;
    if (!row) return '';
    const id = row.chat_channel_id;
    if (id === '' || typeof id !== 'number') return '';
    const ch = chatChannels.find((c) => c.id === id);
    return ch?.name?.trim() ?? '';
  });

  const runTitlePrimary = $derived.by(() => {
    if (activePane !== RUNS_TAB) {
      if (isGraphIngestRun(activePane)) return 'Graph ingest';
      if (isKnowledgeStandaloneRun(activePane)) return 'Knowledge query';
    }
    const row = runIdentitySource;
    const name = titleCharacter?.name?.trim();
    if (name) return name;
    const cid = String(row?.character_id ?? '').trim();
    return cid || '—';
  });

  const runTitleSubtitle = $derived.by(() => {
    if (activePane !== RUNS_TAB) {
      const kind = graphRunKindLabel(activePane);
      const parts: string[] = [kind];
      const ch = activeChannelLabel;
      if (ch) parts.push(ch);
      else if (runIdentitySource?.chat_channel_id !== '' && runIdentitySource?.chat_channel_id != null) {
        parts.push(`Channel ${runIdentitySource.chat_channel_id}`);
      }
      return parts.join(' · ');
    }
    const parts: string[] = [];
    const ch = activeChannelLabel;
    if (ch) parts.push(ch);
    else if (runIdentitySource?.chat_channel_id !== '' && runIdentitySource?.chat_channel_id != null) {
      parts.push(`Channel ${runIdentitySource.chat_channel_id}`);
    }
    return parts.join(' · ');
  });

  const runIdFirstCardDisplay = $derived.by(() => {
    if (activePane === RUNS_TAB) return '';
    const s = String(activePane).trim();
    return s.slice(0, RUN_ID_FIRST_CARD_CHARS);
  });

  const toolbarTotalCostLabel = $derived.by(() => {
    const agg = activeRunAggregate;
    if (!agg) return '';
    const raw = agg.cost_usd;
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '';
    return formatUsdCostDisplay(n) || (n === 0 ? '$0.00' : '');
  });

  const toolbarElapsedLabel = $derived.by(() => {
    const agg = activeRunAggregate;
    if (!agg) return '';
    const raw = agg.elapsed_ms;
    if (raw === '') return '';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '';
    return formatAgentElapsedMs(n);
  });

  const headerFieldList = GRAPH_RUN_HEADER_TAB_FIELDS;
  const nodeFieldList = GRAPH_RUN_NODE_TABLE_FIELDS;
  const nodeDetailFieldList = GRAPH_RUN_HEADER_FIELDS;
  const nodeDetailRow = $derived.by((): GraphLedgerRow | null => {
    if (nodeDetailRowId === null) return null;
    return timeline.find((r) => r.id === nodeDetailRowId) ?? null;
  });

  /* Narrowing character filter makes the selected channel invalid — clear channel so the table doesn’t go empty silently. */
  $effect(() => {
    const cid = tableFilters.filters.gr_char.trim();
    const chSel = tableFilters.filters.gr_chan.trim();
    if (!chSel) return;
    const num = Number(chSel);
    if (!Number.isFinite(num)) return;
    const chan = channelById.get(num);
    if (cid && chan && chan.character_id !== cid) {
      tableFilters.set('gr_chan', '');
    }
  });

  $effect(() => {
    void timeline;
    if (activePane === RUNS_TAB) return;
    const sid = selectedNodeRowId;
    if (sid !== null && !timeline.some((r) => r.id === sid)) {
      selectedNodeRowId = null;
    }
    const did = nodeDetailRowId;
    if (did !== null && !timeline.some((r) => r.id === did)) {
      nodeDetailRowId = null;
    }
  });

  $effect(() => {
    if (activePane === RUNS_TAB) {
      titleCharacter = null;
      return;
    }
    const cid = String(runIdentitySource?.character_id ?? '').trim();
    if (!cid) {
      titleCharacter = null;
      return;
    }
    titleCharacter = null;
    let cancelled = false;
    void getCharacter(cid)
      .then((res) => {
        if (cancelled) return;
        titleCharacter = res.data;
      })
      .catch(() => {
        if (!cancelled) titleCharacter = null;
      });
    return () => {
      cancelled = true;
    };
  });

  async function loadChatChannels() {
    try {
      chatChannels = (await listChatChannels()).data;
    } catch {
      // apiRequest throws on failure; leave the last loaded channels visible.
    }
  }

  async function loadCharacters() {
    try {
      characters = (await listCharacters()).data;
    } catch {
      // apiRequest throws on failure; leave the last loaded characters visible.
    }
  }

  async function loadInitial() {
    error = '';
    offsets = {};
    historySkipFromEnd = 0;
    hasMoreRuns = false;
    const result = await graphRunsFetchInitialLedger();
    if (!result.ok) {
      error = result.error;
      return;
    }
    rows = result.rows;
    offsets = result.offsets;
    hasMoreRuns = result.hasMore;
    historySkipFromEnd = result.rows.length;
  }

  async function loadMoreRuns() {
    if (!hasMoreRuns || loadingMoreRuns) return;
    loadingMoreRuns = true;
    try {
      const result = await graphRunsLoadMoreLedger(historySkipFromEnd);
      if (!result.ok) {
        error = result.error;
        return;
      }
      const existingIds = new Set(rows.map((row) => row.id));
      const older = result.rows.filter((row) => !existingIds.has(row.id));
      if (older.length > 0) {
        rows = [...rows, ...older];
      }
      hasMoreRuns = result.hasMore;
      historySkipFromEnd += result.rows.length;
    } finally {
      loadingMoreRuns = false;
    }
  }

  async function poll() {
    const result = await graphRunsPollLedgerTail(offsets);
    if (!result.ok) return;
    offsets = result.offsets;
    if (result.rows.length > 0) {
      rows = [...rows, ...result.rows].slice(-1000);
    }
  }

  async function resolveLangsmithUrl(runId: string) {
    try {
      const res = await getGraphRunLangsmithUrl(runId);
      if (activeRunId !== runId) return;
      langsmithUrlByRun[runId] = res.data.langsmith_url ?? undefined;
    } catch {
      if (activeRunId !== runId) return;
      langsmithUrlByRun[runId] = undefined;
    }
    langsmithUrlByRun = { ...langsmithUrlByRun };
  }

  async function loadRunDetail(runId: string) {
    langsmithUrlByRun[runId] = undefined;
    langsmithUrlByRun = { ...langsmithUrlByRun };
    try {
      const response = await getGraphRun(runId);
      timelineByRun[runId] = response.data.rows;
      aggregateByRun[runId] = response.data.aggregate ?? null;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      void resolveLangsmithUrl(runId);
      traces.loadFor(runId);
    } catch {
      timelineByRun[runId] = [];
      aggregateByRun[runId] = null;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      langsmithUrlByRun[runId] = undefined;
      langsmithUrlByRun = { ...langsmithUrlByRun };
    }
  }

  async function openRunTab(runId: string) {
    const alreadyOpen = openRunIds.includes(runId);
    if (!alreadyOpen) {
      openRunIds = [...openRunIds, runId];
    }
    activeRunId = runId;
    selectedNodeRowId = null;
    nodeDetailRowId = null;
    traces.resetOpen();
    closeEvalRow();
    if (!alreadyOpen) {
      await loadRunDetail(runId);
    }
  }

  function closeRunTab(runId: string) {
    openRunIds = openRunIds.filter((id) => id !== runId);
    delete timelineByRun[runId];
    delete aggregateByRun[runId];
    delete langsmithUrlByRun[runId];
    timelineByRun = { ...timelineByRun };
    aggregateByRun = { ...aggregateByRun };
    langsmithUrlByRun = { ...langsmithUrlByRun };
    traces.clearFor(runId);
    if (activeRunId === runId) {
      activeRunId = null;
    }
    selectedNodeRowId = null;
    nodeDetailRowId = null;
    traces.resetOpen();
    closeEvalRow();
  }

  function showRunsOnly() {
    activeRunId = null;
    selectedNodeRowId = null;
    nodeDetailRowId = null;
    traces.resetOpen();
    closeEvalRow();
  }

  function refreshMain() {
    void loadInitial();
  }

  function toggleNodeRowSelection(compositeRowId: string) {
    if (nodeDetailRowId !== null) {
      selectedNodeRowId = compositeRowId;
      nodeDetailRowId = compositeRowId;
      return;
    }
    selectedNodeRowId = selectedNodeRowId === compositeRowId ? null : compositeRowId;
  }

  function openNodeDetails(row: GraphLedgerRow) {
    selectedNodeRowId = row.id;
    nodeDetailRowId = row.id;
  }

  function closeNodeDetails() {
    nodeDetailRowId = null;
  }

  function runSourceRowForOpenTab(runId: string): GraphLedgerRow | null {
    const fromInspect = aggregateByRun[runId];
    if (fromInspect) return fromInspect;
    const fromTail = rows.find((r) => r.run_id === runId && String(r.row_kind) === 'run');
    if (fromTail) return fromTail;
    const tl = timelineByRun[runId] ?? [];
    const runRow = tl.find((r) => String(r.row_kind) === 'run');
    if (runRow) return runRow;
    return tl[0] ?? null;
  }

  function runTabDisplayLabel(runId: string): string {
    const row = runSourceRowForOpenTab(runId);
    const preview = String(row?.input_preview ?? '').trim();
    if (preview.length > 0) return preview;
    return trimRunIdForList(runId);
  }

  function runTabTooltip(runId: string): string {
    const row = runSourceRowForOpenTab(runId);
    const preview = String(row?.input_preview ?? '').trim();
    if (preview.length > 0) return `${runId} — ${preview}`;
    return runId;
  }

  function toggleRunDetailCards() {
    uiPrefs.toggleRunDetailCards();
  }

  function onEscapeKey(ev: KeyboardEvent) {
    if (ev.key !== 'Escape') return;
    if (activePane === RUNS_TAB) return;
    const focus = ev.target instanceof HTMLElement ? ev.target : null;
    if (focus?.closest('input, textarea, select, [contenteditable="true"]')) return;
    ev.preventDefault();
    // Eval-detail bridge dialogs close first (the stacked per-search trace, then the row dialog).
    if (rowTraces.activeTrace !== null) {
      rowTraces.closeTrace();
      return;
    }
    if (activeEvalRow !== null) {
      closeEvalRow();
      return;
    }
    if (traces.ingestTraceStep !== null) {
      traces.closeIngestTrace();
      return;
    }
    if (traces.retrievalTraceStep !== null) {
      traces.closeRetrievalTrace();
      return;
    }
    if (nodeDetailRowId !== null) {
      closeNodeDetails();
      return;
    }
    closeRunTab(activePane);
  }

  /** Call from page `onMount` — restores prefs, starts polling, registers Esc + cleanup on destroy. */
  function mount(): () => void {
    void (async () => {
      await loadInitial();
      const runFromUrl = new URLSearchParams(window.location.search).get('run')?.trim();
      if (runFromUrl) {
        await openRunTab(runFromUrl);
      }
    })();
    void loadChatChannels();
    void loadCharacters();
    uiPrefs.initialize();
    const stopPoll = runsPoller.start();
    window.addEventListener('keydown', onEscapeKey);
    return () => {
      stopPoll();
      window.removeEventListener('keydown', onEscapeKey);
    };
  }

  return {
    get activePane() {
      return activePane;
    },
    get openRunIds() {
      return openRunIds;
    },
    get runDetailCardsExpanded() {
      return uiPrefs.runDetailCardsExpanded;
    },
    get filterCharacterId() {
      return tableFilters.filters.gr_char;
    },
    set filterCharacterId(v: string) {
      setGraphRunsFilter('gr_char', v);
    },
    get filterChannelId() {
      return tableFilters.filters.gr_chan;
    },
    set filterChannelId(v: string) {
      setGraphRunsFilter('gr_chan', v);
    },
    get filterStatus() {
      return tableFilters.filters.gr_status;
    },
    set filterStatus(v: string) {
      setGraphRunsFilter('gr_status', v);
    },
    get filterRunKind() {
      return tableFilters.filters.gr_kind as GraphRunKindFilter;
    },
    set filterRunKind(v: GraphRunKindFilter) {
      setGraphRunsFilter('gr_kind', v);
    },
    get previewSearch() {
      return tableFilters.filters.gr_q;
    },
    set previewSearch(v: string) {
      setGraphRunsFilter('gr_q', v);
    },
    get error() {
      return error;
    },
    get hasMoreRuns() {
      return hasMoreRuns;
    },
    get loadingMoreRuns() {
      return loadingMoreRuns;
    },
    get visibleRows() {
      return visibleRows;
    },
    get charactersForFilterDropdown() {
      return charactersForFilterDropdown;
    },
    get channelsForFilterDropdown() {
      return channelsForFilterDropdown;
    },
    get statusesForFilterDropdown() {
      return statusesForFilterDropdown;
    },
    get characterMap() {
      return characterMap;
    },
    get channelById() {
      return channelById;
    },
    get activeRunAggregate() {
      return activeRunAggregate;
    },
    get langsmithUrlForActive() {
      return langsmithUrlForActive;
    },
    get runIdentitySource() {
      return runIdentitySource;
    },
    get titleCharacter() {
      return titleCharacter;
    },
    get runTitlePrimary() {
      return runTitlePrimary;
    },
    get runTitleSubtitle() {
      return runTitleSubtitle;
    },
    get runIdFirstCardDisplay() {
      return runIdFirstCardDisplay;
    },
    get toolbarElapsedLabel() {
      return toolbarElapsedLabel;
    },
    get toolbarTotalCostLabel() {
      return toolbarTotalCostLabel;
    },
    get timeline() {
      return timeline;
    },
    get selectedNodeRowId() {
      return selectedNodeRowId;
    },
    set selectedNodeRowId(v: string | null) {
      selectedNodeRowId = v;
    },
    get headerFieldList() {
      return headerFieldList;
    },
    get nodeFieldList() {
      return nodeFieldList;
    },
    get nodeDetailFieldList() {
      return nodeDetailFieldList;
    },
    get nodeDetailRow() {
      return nodeDetailRow;
    },
    /** Retrieval + ingest trace sub-model (markers, open-dialog targets, arrow-nav) — its own
     * reactive getters + open/close/step methods are consumed directly as `ctrl.traces.*`. */
    get traces() {
      return traces;
    },
    /** Eval-detail bridge surface — the resolved row, its leg columns, the (stacked) trace dialog
     * controller, and the open/close actions the `memory_recall` marker drives. */
    get activeEvalRow() {
      return activeEvalRow;
    },
    get evalRowLoadingRunId() {
      return evalRowLoadingRunId;
    },
    get evalRowLegColumns() {
      return evalRowLegColumns;
    },
    get evalRowTraces() {
      return rowTraces;
    },
    openEvalRowForNode,
    closeEvalRow,
    RUNS_TAB,
    mount,
    showRunsOnly,
    openRunTab,
    closeRunTab,
    refreshMain,
    loadMoreRuns,
    toggleRunDetailCards,
    toggleNodeRowSelection,
    openNodeDetails,
    closeNodeDetails,
    runTabDisplayLabel,
    runTabTooltip
  };
}

export type GraphRunsPageController = ReturnType<typeof createGraphRunsPageController>;
