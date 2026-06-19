/**
 * Orchestration for the standalone Memories admin page: workspace long-term
 * memory (Graphiti facts) list, filters, view-JSON / delete / clear dialogs.
 *
 * Extracted from the old monolithic Graph Runs controller when Memories was
 * promoted to its own page (Graph runs itself moved under the Logs page as a
 * tab). Runs-ledger concerns live in `graph-runs/state/graph-runs-controller`.
 *
 * Follows getters for `$derived` consumers (avoid returning shorthand `$derived`
 * from a factory — that captures a stale value).
 */
import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
import { listCharacters, type CharacterRow } from '$lib/api/characters';
import {
  fetchGraphChunksDetail,
  listKnowledgeGraphGroups,
  type GraphChunkDetail,
  type GraphGroup
} from '$lib/api/knowledge';
import { preserveStickyAnchorAround } from '$lib/components/page/table/preserve-sticky-anchor';
import {
  memoryChunkIds,
  memoryField,
  memoryId,
  memoryRowPassesFilters,
  memorySortSeconds
} from '../shared/memory-pure';
import { clearAllMemories, deleteMemories, loadMemoriesList } from './memories-service';
import { createKnowledgeGraphModel } from '$lib/features/knowledge/state/knowledge-graph.svelte';

export function createMemoriesPageController() {
  let chatChannels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);

  // Entity-graph viz (the former Knowledge "Graph" tab, relocated here as the
  // Memories page's second tab). The live SSE subscription is owned at the page
  // level — see `mount` below — not by the panel, so graph deltas keep
  // accumulating in the model even while the user is on the Memories tab. The
  // panel still owns rendering + the initial load() when it mounts.
  let graphError = $state<string | null>(null);
  const graph = createKnowledgeGraphModel({
    setError: (msg) => {
      graphError = msg;
    }
  });

  let memoriesError = $state('');
  let memoriesLoading = $state(false);
  let memoryEnabled = $state<boolean | null>(null);
  let memoriesRows = $state<Record<string, unknown>[]>([]);
  let memoryActionBusy = $state(false);
  let memoryJsonRow = $state<Record<string, unknown> | null>(null);
  let clearMemoriesConfirmOpen = $state(false);

  // Provenance drill-down: the originating conversation turn(s) for a fact. Resolved lazily
  // from the row's chunk_ids via the same chunk-detail endpoint the Graph tab uses (it reads
  // memory episode text from Kuzu). Summaries carry no chunk_ids → an empty "no source" state.
  let memoryProvenanceRow = $state<Record<string, unknown> | null>(null);
  let memoryProvenanceChunks = $state<GraphChunkDetail[]>([]);
  let memoryProvenanceLoading = $state(false);
  let memoryProvenanceError = $state('');
  let provenanceAbort: AbortController | null = null;

  let memorySearch = $state('');
  // Group filter (server-side): '' = the page default (all of the default user's conversation
  // groups via list_all); a group id = that one partition's facts (memory / knowledge / eval).
  // Unlike the other filters (client-side over the loaded rows), changing this RELOADS the list.
  // Options are sourced from the same /knowledge/graph/groups endpoint the Graph tab uses.
  let memoryGroups = $state<GraphGroup[]>([]);
  let memoryFilterGroupId = $state('');
  let memoryFilterCharacterId = $state('');
  let memoryFilterSource = $state('');
  // Date-range filter (yyyy-mm-dd, from <input type="date">). Doubles as a delete scope.
  let memoryFilterDateFrom = $state('');
  let memoryFilterDateTo = $state('');

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

  // Parse the date-range inputs once into ms epoch (NaN = unset). "to" is end-of-day inclusive.
  const memoryDateFromMs = $derived.by((): number => {
    const v = memoryFilterDateFrom.trim();
    if (!v) return NaN;
    return new Date(`${v}T00:00:00`).getTime();
  });
  const memoryDateToMs = $derived.by((): number => {
    const v = memoryFilterDateTo.trim();
    if (!v) return NaN;
    return new Date(`${v}T23:59:59.999`).getTime();
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
        sourceFilter: memoryFilterSource,
        searchNeedle: memorySearchNeedle,
        dateFromMs: memoryDateFromMs,
        dateToMs: memoryDateToMs,
        characterMap,
        channelById
      })
    )
  );

  const charactersForFilterDropdown = $derived.by(() =>
    [...characters].sort((a, b) => a.name.localeCompare(b.name))
  );

  // Group dropdown options (logical labels from the backend's group policy). The backend
  // already returns them in a friendly order (knowledge → memory → eval → other); we keep it.
  const memoryGroupsForFilterDropdown = $derived.by((): { value: string; label: string }[] =>
    memoryGroups.map((g) => ({ value: g.id, label: g.label }))
  );

  // group_id → logical label (Knowledge / Memory · char / Eval · …), for the table's Group
  // column. Falls back to the raw id in the column when a row's group isn't in the list.
  const memoryGroupLabelById = $derived.by((): Map<string, string> => {
    const m = new Map<string, string>();
    for (const g of memoryGroups) m.set(g.id, g.label);
    return m;
  });

  // True when any filter is narrowing the view — defines the clear scope (filtered → delete the
  // shown rows by id; unfiltered → wipe all of the default user's memory). A selected group counts
  // as filtered so clearing a knowledge/eval group never falls through to the all-memory clear.
  const memoryFiltersActive = $derived(
    memoryFilterGroupId.trim() !== '' ||
      memoryFilterCharacterId.trim() !== '' ||
      memoryFilterSource.trim() !== '' ||
      memoryFilterDateFrom.trim() !== '' ||
      memoryFilterDateTo.trim() !== '' ||
      memorySearchNeedle !== ''
  );

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

  async function loadMemories() {
    memoriesError = '';
    memoriesLoading = true;
    try {
      // Scope to the selected partition when one is chosen; '' loads the page default.
      const r = await loadMemoriesList(memoryFilterGroupId.trim() || undefined);
      memoryEnabled = r.memoryEnabled;
      memoriesRows = r.memories;
      memoriesError = r.error;
    } finally {
      memoriesLoading = false;
    }
  }

  // Populate the group selector from the same endpoint the Graph tab uses (all partitions:
  // knowledge / memory / eval). Failure is non-fatal — the dropdown just stays at its default
  // "All memory" option; the list itself is unaffected.
  async function loadMemoryGroups() {
    const res = await listKnowledgeGraphGroups();
    if (res.ok && res.data) memoryGroups = res.data.groups;
  }

  function closeMemoryJsonDialog() {
    memoryJsonRow = null;
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

  // Open the provenance dialog and resolve the row's chunk_ids → source turn text.
  // apiRequest throws on error/abort, so the lookup is guarded; a superseding open aborts
  // the previous in-flight fetch.
  async function showMemoryProvenance(row: Record<string, unknown>) {
    provenanceAbort?.abort();
    memoryProvenanceRow = row;
    memoryProvenanceChunks = [];
    memoryProvenanceError = '';
    const ids = memoryChunkIds(row);
    if (ids.length === 0) {
      memoryProvenanceLoading = false;
      return; // summaries (and any unciteable fact) carry no chunk provenance
    }
    memoryProvenanceLoading = true;
    const ctrl = new AbortController();
    provenanceAbort = ctrl;
    try {
      const res = await fetchGraphChunksDetail(ids, ctrl.signal);
      if (ctrl.signal.aborted) return;
      memoryProvenanceChunks = res.data?.chunks ?? [];
    } catch (e) {
      if (ctrl.signal.aborted) return; // expected when superseded / closed
      memoryProvenanceError = e instanceof Error ? e.message : 'Failed to load source turns.';
    } finally {
      if (!ctrl.signal.aborted) memoryProvenanceLoading = false;
    }
  }

  function closeMemoryProvenance() {
    provenanceAbort?.abort();
    provenanceAbort = null;
    memoryProvenanceRow = null;
    memoryProvenanceChunks = [];
    memoryProvenanceError = '';
    memoryProvenanceLoading = false;
  }

  async function confirmClearMemories() {
    memoryActionBusy = true;
    memoriesError = '';
    try {
      // The active filters define the delete scope: no filter → wipe everything (efficient
      // group clear, also removes the episodes); any filter (incl. a selected group) → delete
      // exactly the shown rows by edge id.
      if (memoryFiltersActive) {
        const ids = visibleMemoriesRows.map((row) => memoryId(row)).filter(Boolean);
        await deleteMemories(ids);
      } else {
        await clearAllMemories();
      }
      clearMemoriesConfirmOpen = false;
      await loadMemories();
    } catch (e) {
      memoriesError = e instanceof Error ? e.message : 'Failed to clear memories.';
    } finally {
      memoryActionBusy = false;
    }
  }

  /**
   * Call from page `onMount` — loads memories and the character/channel lookups
   * used by filters, and opens the page-level entity-graph SSE subscription.
   * Returns the teardown so live deltas stop when the page unmounts.
   */
  function mount(): () => void {
    void loadMemories();
    void loadMemoryGroups();
    void loadChatChannels();
    void loadCharacters();
    return graph.connectEvents();
  }

  return {
    get graph() {
      return graph;
    },
    get graphError() {
      return graphError;
    },
    get memoriesError() {
      return memoriesError;
    },
    get memoriesLoading() {
      return memoriesLoading;
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
    get charactersForFilterDropdown() {
      return charactersForFilterDropdown;
    },
    get memoryGroupsForFilterDropdown() {
      return memoryGroupsForFilterDropdown;
    },
    get memoryGroupLabelById() {
      return memoryGroupLabelById;
    },
    get sourcesForMemoryFilterDropdown() {
      return sourcesForMemoryFilterDropdown;
    },
    get characterMap() {
      return characterMap;
    },
    get channelById() {
      return channelById;
    },
    get memoryActionBusy() {
      return memoryActionBusy;
    },
    get memoryJsonRow() {
      return memoryJsonRow;
    },
    get memoryProvenanceRow() {
      return memoryProvenanceRow;
    },
    get memoryProvenanceChunks() {
      return memoryProvenanceChunks;
    },
    get memoryProvenanceLoading() {
      return memoryProvenanceLoading;
    },
    get memoryProvenanceError() {
      return memoryProvenanceError;
    },
    get clearMemoriesConfirmOpen() {
      return clearMemoriesConfirmOpen;
    },
    get memorySearch() {
      return memorySearch;
    },
    set memorySearch(v: string) {
      memorySearch = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterGroupId() {
      return memoryFilterGroupId;
    },
    set memoryFilterGroupId(v: string) {
      if (v === memoryFilterGroupId) return;
      memoryFilterGroupId = v;
      // Group scope is server-side — reload the list for the newly selected partition.
      void loadMemories();
    },
    get memoryFilterCharacterId() {
      return memoryFilterCharacterId;
    },
    set memoryFilterCharacterId(v: string) {
      memoryFilterCharacterId = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterDateFrom() {
      return memoryFilterDateFrom;
    },
    set memoryFilterDateFrom(v: string) {
      memoryFilterDateFrom = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterDateTo() {
      return memoryFilterDateTo;
    },
    set memoryFilterDateTo(v: string) {
      memoryFilterDateTo = v;
      preserveStickyAnchorAround();
    },
    get memoryFilterSource() {
      return memoryFilterSource;
    },
    set memoryFilterSource(v: string) {
      memoryFilterSource = v;
      preserveStickyAnchorAround();
    },
    mount,
    loadMemories,
    refreshMemories: loadMemories,
    closeMemoryJsonDialog,
    closeClearMemoriesDialog,
    requestClearMemoriesConfirm,
    showMemoryJsonRow,
    showMemoryProvenance,
    closeMemoryProvenance,
    confirmClearMemories
  };
}

export type MemoriesPageController = ReturnType<typeof createMemoriesPageController>;
