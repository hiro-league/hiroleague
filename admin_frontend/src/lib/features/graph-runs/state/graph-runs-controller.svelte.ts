/**
 * Orchestration for Graph Runs admin UI: ledger tail polling, inspect tabs, filters, memories, dialogs.
 * Follows getters for `$derived` consumers (avoid returning shorthand `$derived` from factory — stale capture).
 */
import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
import { getCharacter, listCharacters, type CharacterDetail, type CharacterRow } from '$lib/api/characters';
import { preserveStickyAnchorAround } from '$lib/components/page/table/preserve-sticky-anchor';
import {
  getGraphRun,
  getGraphRunLangsmithUrl,
  GRAPH_RUN_HEADER_FIELDS,
  GRAPH_RUN_HEADER_TAB_FIELDS,
  GRAPH_RUN_NODE_TABLE_FIELDS,
  type GraphLedgerRow
} from '$lib/api/graph-runs';
import {
  formatAgentElapsedMs,
  formatUsdCostDisplay
} from '$lib/features/chat-channels/messages/agent-message-meta';
import { createGraphRunsPreferences } from '$lib/preferences/graph-runs-preferences.svelte';
import {
  MEMORIES_TAB,
  memoryField,
  memoryId,
  memoryRowPassesFilters,
  memorySortSeconds,
  RUN_ID_FIRST_CARD_CHARS,
  RUNS_TAB,
  trimRunIdForList,
  isKnowledgeStandaloneRun,
  graphRunKindLabel,
  graphRunKindMatchesFilter,
  type ActivePane,
  type GraphRunKindFilter,
} from '../graph-runs-pure';
import { graphRunsFetchInitialLedger, graphRunsLoadMoreLedger, graphRunsPollLedgerTail } from './graph-runs-ledger-service';
import {
  graphRunsClearAllMemories,
  graphRunsDeleteMemory,
  graphRunsLoadMemoriesList
} from './graph-runs-memory-service';

export function createGraphRunsPageController() {
  const uiPrefs = createGraphRunsPreferences();
  let rows = $state<GraphLedgerRow[]>([]);
  let openRunIds = $state<string[]>([]);
  /**
   * Active opened-run inspector id. Independent of the primary `?tab=` pref
   * (a run can be open while the user is on the Memories pane). The derived
   * `activePane` below collapses both into the legacy single value.
   */
  let activeRunId = $state<string | null>(null);
  const activePane = $derived<ActivePane>(
    uiPrefs.activeTab === MEMORIES_TAB ? MEMORIES_TAB : (activeRunId ?? RUNS_TAB)
  );

  let timelineByRun = $state<Record<string, GraphLedgerRow[]>>({});
  let langsmithUrlByRun = $state<Record<string, string | undefined>>({});
  let aggregateByRun = $state<Record<string, GraphLedgerRow | null>>({});
  let chatChannels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);
  let titleCharacter = $state<CharacterDetail | null>(null);

  let error = $state('');
  let memoriesError = $state('');
  let memoriesLoading = $state(false);
  let memoryEnabled = $state<boolean | null>(null);
  let memoriesRows = $state<Record<string, unknown>[]>([]);
  let memoryActionBusy = $state(false);
  let memoryJsonRow = $state<Record<string, unknown> | null>(null);
  let clearMemoriesConfirmOpen = $state(false);
  let deleteMemoryTarget = $state<Record<string, unknown> | null>(null);

  let offsets: Record<string, number> = {};
  let timer: ReturnType<typeof setInterval> | null = null;
  let hasMoreRuns = $state(false);
  let historySkipFromEnd = $state(0);
  let loadingMoreRuns = $state(false);

  let selectedNodeRowId = $state<string | null>(null);
  let nodeDetailRowId = $state<string | null>(null);

  let previewSearch = $state('');
  let filterCharacterId = $state('');
  let filterChannelId = $state('');
  let filterStatus = $state('');
  let filterRunKind = $state<GraphRunKindFilter>('');

  let memorySearch = $state('');
  let memoryFilterCharacterId = $state('');
  let memoryFilterChannelId = $state('');
  let memoryFilterSource = $state('');

  const previewSearchNeedle = $derived(previewSearch.trim().toLowerCase());
  const memorySearchNeedle = $derived(memorySearch.trim().toLowerCase());

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

  const sortedMemoriesRows = $derived.by(() =>
    [...memoriesRows].sort((a, b) => memorySortSeconds(b) - memorySortSeconds(a))
  );

  const channelsForMemoryFilterDropdown = $derived.by(() => {
    const cid = memoryFilterCharacterId.trim();
    const base = cid ? chatChannels.filter((c) => c.character_id === cid) : [...chatChannels];
    return base.sort((a, b) => a.name.localeCompare(b.name));
  });

  const sourcesForMemoryFilterDropdown = $derived.by((): { value: string; label: string }[] => {
    const raw = new Set<string>();
    let anyEmpty = false;
    for (const row of memoriesRows) {
      const s = String(memoryField(row, 'source') ?? '').trim();
      if (s === '') anyEmpty = true;
      else raw.add(s);
    }
    const out: { value: string; label: string }[] = [];
    if (anyEmpty) out.push({ value: '__empty__', label: '(no source)' });
    for (const s of [...raw].sort((a, b) => a.localeCompare(b))) {
      out.push({ value: s, label: s });
    }
    return out;
  });

  const visibleMemoriesRows = $derived.by(() =>
    sortedMemoriesRows.filter((row) =>
      memoryRowPassesFilters(row, {
        characterId: memoryFilterCharacterId,
        channelId: memoryFilterChannelId,
        sourceFilter: memoryFilterSource,
        searchNeedle: memorySearchNeedle,
        characterMap,
        channelById
      })
    )
  );

  const charactersForFilterDropdown = $derived.by(() =>
    [...characters].sort((a, b) => a.name.localeCompare(b.name))
  );

  const channelsForFilterDropdown = $derived.by(() => {
    const cid = filterCharacterId.trim();
    const base = cid ? chatChannels.filter((c) => c.character_id === cid) : [...chatChannels];
    return base.sort((a, b) => a.name.localeCompare(b.name));
  });

  const statusesForFilterDropdown = $derived.by((): { value: string; label: string }[] => {
    const raw = new Set<string>();
    let anyEmpty = false;
    for (const r of rows) {
      const s = String(r.status ?? '').trim();
      if (s === '') anyEmpty = true;
      else raw.add(s);
    }
    const out: { value: string; label: string }[] = [];
    if (anyEmpty) out.push({ value: '__empty__', label: '(no status)' });
    for (const s of [...raw].sort((a, b) => a.localeCompare(b))) {
      out.push({ value: s, label: s });
    }
    return out;
  });

  const visibleRows = $derived.by(() => {
    const q = previewSearchNeedle;
    const charF = filterCharacterId.trim();
    const chanF = filterChannelId.trim();
    const stF = filterStatus;
    const kindF = filterRunKind;
    const sorted = [...rows].sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0));
    let filtered = sorted;
    if (kindF) {
      filtered = filtered.filter((r) => graphRunKindMatchesFilter(String(r.run_id ?? ''), kindF));
    }
    if (charF) {
      filtered = filtered.filter((r) => String(r.character_id ?? '').trim() === charF);
    }
    if (chanF) {
      const n = Number(chanF);
      if (Number.isFinite(n)) {
        filtered = filtered.filter((r) => r.chat_channel_id === n);
      }
    }
    if (stF) {
      if (stF === '__empty__') {
        filtered = filtered.filter((r) => !String(r.status ?? '').trim());
      } else {
        filtered = filtered.filter((r) => String(r.status ?? '').trim() === stF);
      }
    }
    if (q) {
      filtered = filtered.filter((r) => {
        const inp = String(r.input_preview ?? '').toLowerCase();
        const outp = String(r.output_preview ?? '').toLowerCase();
        return inp.includes(q) || outp.includes(q);
      });
    }
    return filtered.slice(0, 500);
  });

  const timeline = $derived(
    activePane === RUNS_TAB || activePane === MEMORIES_TAB ? [] : (timelineByRun[activePane] ?? [])
  );

  const activeRunAggregate = $derived.by(() => {
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) return null;
    const rid = activePane;
    const fromInspect = aggregateByRun[rid];
    if (fromInspect) return fromInspect;
    return rows.find((row) => row.run_id === rid && String(row.row_kind) === 'run') ?? null;
  });

  const langsmithUrlForActive = $derived(
    activePane === RUNS_TAB || activePane === MEMORIES_TAB ? null : (langsmithUrlByRun[activePane] ?? null)
  );

  const runIdentitySource = $derived.by((): GraphLedgerRow | null => {
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) return null;
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
    if (activePane !== RUNS_TAB && activePane !== MEMORIES_TAB) {
      if (isKnowledgeStandaloneRun(activePane)) return 'Knowledge query';
    }
    const row = runIdentitySource;
    const name = titleCharacter?.name?.trim();
    if (name) return name;
    const cid = String(row?.character_id ?? '').trim();
    return cid || '—';
  });

  const runTitleSubtitle = $derived.by(() => {
    if (activePane !== RUNS_TAB && activePane !== MEMORIES_TAB) {
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
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) return '';
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
    const cid = filterCharacterId.trim();
    const chSel = filterChannelId.trim();
    if (!chSel) return;
    const num = Number(chSel);
    if (!Number.isFinite(num)) return;
    const chan = channelById.get(num);
    if (cid && chan && chan.character_id !== cid) {
      filterChannelId = '';
    }
  });

  $effect(() => {
    const cid = memoryFilterCharacterId.trim();
    const chSel = memoryFilterChannelId.trim();
    if (!chSel) return;
    const num = Number(chSel);
    if (!Number.isFinite(num)) return;
    const chan = channelById.get(num);
    if (cid && chan && chan.character_id !== cid) {
      memoryFilterChannelId = '';
    }
  });

  $effect(() => {
    void timeline;
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) return;
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
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) {
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
    void getCharacter(cid).then((res) => {
      if (cancelled) return;
      titleCharacter = res.ok && res.data ? res.data : null;
    });
    return () => {
      cancelled = true;
    };
  });

  async function loadChatChannels() {
    const response = await listChatChannels();
    if (response.ok && response.data) {
      chatChannels = response.data;
    }
  }

  async function loadCharacters() {
    const response = await listCharacters();
    if (response.ok && response.data) {
      characters = response.data;
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
    const res = await getGraphRunLangsmithUrl(runId);
    if (activeRunId !== runId) return;
    if (res.ok && res.data) {
      langsmithUrlByRun[runId] = res.data.langsmith_url ?? undefined;
    } else {
      langsmithUrlByRun[runId] = undefined;
    }
    langsmithUrlByRun = { ...langsmithUrlByRun };
  }

  async function loadRunDetail(runId: string) {
    langsmithUrlByRun[runId] = undefined;
    langsmithUrlByRun = { ...langsmithUrlByRun };
    const response = await getGraphRun(runId);
    if (response.ok && response.data) {
      timelineByRun[runId] = response.data.rows;
      aggregateByRun[runId] = response.data.aggregate ?? null;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      void resolveLangsmithUrl(runId);
    } else if (!response.ok) {
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
    // Opening a run inspector implies the runs primary tab.
    if (uiPrefs.activeTab !== RUNS_TAB) {
      void uiPrefs.setActiveTab(RUNS_TAB);
    }
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
    if (activeRunId === runId) {
      activeRunId = null;
    }
    selectedNodeRowId = null;
    nodeDetailRowId = null;
  }

  function showRunsOnly() {
    activeRunId = null;
    selectedNodeRowId = null;
    nodeDetailRowId = null;
    if (uiPrefs.activeTab !== RUNS_TAB) {
      void uiPrefs.setActiveTab(RUNS_TAB);
    }
  }

  /** Primary “Graph runs” pill: leaves Memories without clearing an opened inspector (# two-tier tabs). */
  function activateGraphRunsPrimaryTab() {
    if (uiPrefs.activeTab === MEMORIES_TAB) {
      void uiPrefs.setActiveTab(RUNS_TAB);
      selectedNodeRowId = null;
      nodeDetailRowId = null;
    }
  }

  function showMemories() {
    selectedNodeRowId = null;
    nodeDetailRowId = null;
    void uiPrefs.setActiveTab(MEMORIES_TAB);
    void loadMemories();
  }

  /** Wire-friendly setter for `<AdminTabStrip onSelect>`; dispatches to the
   * right action so side-effects (load memories, preserve open inspector) are
   * preserved. */
  function setPrimaryTab(id: 'runs' | 'memories') {
    if (id === MEMORIES_TAB) {
      showMemories();
    } else {
      activateGraphRunsPrimaryTab();
    }
  }

  function closeMemoryJsonDialog() {
    memoryJsonRow = null;
  }

  function openDeleteMemoryDialog(row: Record<string, unknown>) {
    if (!memoryId(row)) return;
    deleteMemoryTarget = row;
  }

  function closeDeleteMemoryDialog() {
    if (!memoryActionBusy) deleteMemoryTarget = null;
  }

  function closeClearMemoriesDialog() {
    if (!memoryActionBusy) clearMemoriesConfirmOpen = false;
  }

  function requestClearMemoriesConfirm() {
    clearMemoriesConfirmOpen = true;
  }

  function showMemoryJsonRow(row: Record<string, unknown>) {
    memoryJsonRow = row;
  }

  async function confirmClearMemories() {
    memoryActionBusy = true;
    memoriesError = '';
    try {
      await graphRunsClearAllMemories();
      clearMemoriesConfirmOpen = false;
      await loadMemories();
    } catch (e) {
      memoriesError = e instanceof Error ? e.message : 'Failed to clear memories.';
    } finally {
      memoryActionBusy = false;
    }
  }

  async function confirmDeleteMemory() {
    const target = deleteMemoryTarget;
    const id = target ? memoryId(target) : '';
    if (!id) return;
    memoryActionBusy = true;
    memoriesError = '';
    try {
      await graphRunsDeleteMemory(id);
      deleteMemoryTarget = null;
      memoriesRows = memoriesRows.filter((row) => memoryId(row) !== id);
    } catch (e) {
      memoriesError = e instanceof Error ? e.message : 'Failed to delete memory.';
    } finally {
      memoryActionBusy = false;
    }
  }

  async function loadMemories() {
    memoriesError = '';
    memoriesLoading = true;
    try {
      const r = await graphRunsLoadMemoriesList();
      memoryEnabled = r.memoryEnabled;
      memoriesRows = r.memories;
      memoriesError = r.error;
    } finally {
      memoriesLoading = false;
    }
  }

  function refreshMain() {
    if (activePane === MEMORIES_TAB) {
      void loadMemories();
    } else {
      void loadInitial();
    }
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
    if (activePane === RUNS_TAB || activePane === MEMORIES_TAB) return;
    const focus = ev.target instanceof HTMLElement ? ev.target : null;
    if (focus?.closest('input, textarea, select, [contenteditable="true"]')) return;
    ev.preventDefault();
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
    timer = setInterval(poll, 2500);
    window.addEventListener('keydown', onEscapeKey);
    return dispose;
  }

  function dispose(): void {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    window.removeEventListener('keydown', onEscapeKey);
  }

  return {
    get activePane() {
      return activePane;
    },
    get primaryTab() {
      return uiPrefs.activeTab;
    },
    get openRunIds() {
      return openRunIds;
    },
    get runDetailCardsExpanded() {
      return uiPrefs.runDetailCardsExpanded;
    },
    get memoriesLoading() {
      return memoriesLoading;
    },
    get filterCharacterId() {
      return filterCharacterId;
    },
    set filterCharacterId(v: string) {
      filterCharacterId = v;
      // Filter changes shrink the rendered list; preserve sticky chrome y-pos.
      preserveStickyAnchorAround();
    },
    get filterChannelId() {
      return filterChannelId;
    },
    set filterChannelId(v: string) {
      filterChannelId = v;
      preserveStickyAnchorAround();
    },
    get filterStatus() {
      return filterStatus;
    },
    set filterStatus(v: string) {
      filterStatus = v;
      preserveStickyAnchorAround();
    },
    get filterRunKind() {
      return filterRunKind;
    },
    set filterRunKind(v: GraphRunKindFilter) {
      filterRunKind = v;
      preserveStickyAnchorAround();
    },
    get previewSearch() {
      return previewSearch;
    },
    set previewSearch(v: string) {
      previewSearch = v;
      preserveStickyAnchorAround();
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
    get previewSearchNeedle() {
      return previewSearchNeedle;
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
    get memoriesError() {
      return memoriesError;
    },
    get memoryEnabled() {
      return memoryEnabled;
    },
    get sortedMemoriesRows() {
      return sortedMemoriesRows;
    },
    get visibleMemoriesRows() {
      return visibleMemoriesRows;
    },
    get channelsForMemoryFilterDropdown() {
      return channelsForMemoryFilterDropdown;
    },
    get sourcesForMemoryFilterDropdown() {
      return sourcesForMemoryFilterDropdown;
    },
    get memorySearch() {
      return memorySearch;
    },
    set memorySearch(v: string) {
      memorySearch = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterCharacterId() {
      return memoryFilterCharacterId;
    },
    set memoryFilterCharacterId(v: string) {
      memoryFilterCharacterId = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterChannelId() {
      return memoryFilterChannelId;
    },
    set memoryFilterChannelId(v: string) {
      memoryFilterChannelId = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterSource() {
      return memoryFilterSource;
    },
    set memoryFilterSource(v: string) {
      memoryFilterSource = v;
      preserveStickyAnchorAround();
    },
    get memoryActionBusy() {
      return memoryActionBusy;
    },
    get memoryJsonRow() {
      return memoryJsonRow;
    },
    get clearMemoriesConfirmOpen() {
      return clearMemoriesConfirmOpen;
    },
    get deleteMemoryTarget() {
      return deleteMemoryTarget;
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
    RUNS_TAB,
    MEMORIES_TAB,
    mount,
    dispose,
    showRunsOnly,
    activateGraphRunsPrimaryTab,
    showMemories,
    setPrimaryTab,
    openRunTab,
    closeRunTab,
    refreshMain,
    loadMoreRuns,
    toggleRunDetailCards,
    toggleNodeRowSelection,
    openNodeDetails,
    closeNodeDetails,
    runTabDisplayLabel,
    runTabTooltip,
    closeMemoryJsonDialog,
    openDeleteMemoryDialog,
    closeDeleteMemoryDialog,
    closeClearMemoriesDialog,
    requestClearMemoriesConfirm,
    showMemoryJsonRow,
    confirmClearMemories,
    confirmDeleteMemory
  };
}

export type GraphRunsPageController = ReturnType<typeof createGraphRunsPageController>;
