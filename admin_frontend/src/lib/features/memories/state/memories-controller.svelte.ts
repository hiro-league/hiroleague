/**
 * Orchestration for the standalone Memories admin page: workspace long-term
 * memory (Graphiti facts) list, filters, view-JSON / delete / clear dialogs.
 *
 * Scope is memories only. The page's second "Graph" tab (the relocated knowledge
 * entity-graph viz) and its live SSE subscription are owned by the page itself,
 * not this controller. Runs-ledger concerns live in `graph-runs/state/graph-runs-controller`.
 *
 * Follows getters for `$derived` consumers (avoid returning shorthand `$derived`
 * from a factory — that captures a stale value).
 */
import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
import { listCharacters, type CharacterRow } from '$lib/api/characters';
import { listKnowledgeGraphGroups, type GraphGroup } from '$lib/api/knowledge';
import { preserveStickyAnchorAround } from '$lib/components/page/table/preserve-sticky-anchor';
import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
import { useTableSort } from '$lib/components/page/table/use-table-sort.svelte';
import { asTableSortDirection } from '$lib/components/page/table/table-sort-utils';
import {
  DEFAULT_MEMORY_SORT,
  MEMORY_FILTER_KEYS,
  MEMORY_SORT_COLUMNS,
  memoryDateInputMs,
  memoryId,
  memoryRowPassesFilters,
  memorySourceOptions,
  sortMemories,
  type MemoryFilterKey,
  type MemorySortColumn
} from '../shared/memory-pure';
import { clearAllMemories, deleteMemories, loadMemoriesList } from './memories-service';
import { createMemoryProvenance } from './memories-provenance.svelte';

export function createMemoriesPageController() {
  let chatChannels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);

  let memoriesError = $state('');
  let memoriesLoading = $state(false);
  let memoryEnabled = $state<boolean | null>(null);
  let memoriesRows = $state<Record<string, unknown>[]>([]);
  let memoryActionBusy = $state(false);
  let memoryJsonRow = $state<Record<string, unknown> | null>(null);
  let clearMemoriesConfirmOpen = $state(false);

  // Provenance drill-down (originating conversation turn(s) for a fact) is its own module.
  const provenance = createMemoryProvenance();

  // Group filter (server-side): '' = the page default (all of the default user's conversation
  // groups via list_all); a group id = that one partition's facts (memory / knowledge / eval).
  // Unlike the other filters (client-side over the loaded rows), changing this RELOADS the list.
  // Options are sourced from the same /knowledge/graph/groups endpoint the Graph tab uses.
  let memoryGroups = $state<GraphGroup[]>([]);

  // All Memories-table filters live in one URL-synced controller (deep-linkable, survives reload)
  // and column ordering in a sibling sort controller. `setFilter` (below) is the single write path.
  const tableFilters = useTableFilters<MemoryFilterKey>({ keys: MEMORY_FILTER_KEYS, urlSync: true });
  const sort = useTableSort<MemorySortColumn>({
    defaultBy: DEFAULT_MEMORY_SORT.column,
    defaultDirection: DEFAULT_MEMORY_SORT.direction,
    allowed: MEMORY_SORT_COLUMNS,
    urlSync: true,
    sortParam: 'mem_sort',
    directionParam: 'mem_sort_dir'
  });

  const memorySearchQuery = $derived(tableFilters.filters.mem_q);

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

  // group_id → logical label (Knowledge / Memory · char / Eval · …), for the table's Group
  // column. Falls back to the raw id in the column when a row's group isn't in the list.
  const memoryGroupLabelById = $derived.by((): Map<string, string> => {
    const m = new Map<string, string>();
    for (const g of memoryGroups) m.set(g.id, g.label);
    return m;
  });

  const sortedMemoriesRows = $derived(
    sortMemories(memoriesRows, sort.sortBy, asTableSortDirection(sort.direction), {
      characterMap,
      channelById,
      groupLabelById: memoryGroupLabelById
    })
  );

  // Parse the date-range inputs into ms epoch (NaN = unset). "to" is end-of-day inclusive.
  const memoryDateFromMs = $derived(memoryDateInputMs(tableFilters.filters.mem_from));
  const memoryDateToMs = $derived(memoryDateInputMs(tableFilters.filters.mem_to, true));

  const sourcesForMemoryFilterDropdown = $derived(memorySourceOptions(memoriesRows));

  const visibleMemoriesRows = $derived.by(() =>
    sortedMemoriesRows.filter((row) =>
      memoryRowPassesFilters(row, {
        characterId: tableFilters.filters.mem_char,
        sourceFilter: tableFilters.filters.mem_source,
        searchQuery: memorySearchQuery,
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

  // True when any filter is narrowing the view — defines the clear scope (filtered → delete the
  // shown rows by id; unfiltered → wipe all of the default user's memory). A selected group counts
  // as filtered so clearing a knowledge/eval group never falls through to the all-memory clear.
  const memoryFiltersActive = $derived(
    tableFilters.filters.mem_group.trim() !== '' ||
      tableFilters.filters.mem_char.trim() !== '' ||
      tableFilters.filters.mem_source.trim() !== '' ||
      tableFilters.filters.mem_from.trim() !== '' ||
      tableFilters.filters.mem_to.trim() !== '' ||
      memorySearchQuery.trim() !== ''
  );

  /**
   * Single write path for every table filter. Group scope is server-side, so changing it reloads
   * the list for the newly selected partition; the client-side filters just preserve the sticky
   * scroll anchor across the re-render. No-ops when the value is unchanged.
   */
  function setFilter(key: MemoryFilterKey, value: string) {
    if (value === tableFilters.filters[key]) return;
    tableFilters.set(key, value);
    // Group scope is server-side and reloaded by the groupScopeReload effect below
    // (so browser back/forward gets the same reload). Client-side filters only need
    // the sticky scroll anchor preserved across the re-render.
    if (key !== 'mem_group') {
      preserveStickyAnchorAround();
    }
  }

  // Reload the list whenever the server-side group partition changes from ANY source —
  // setFilter or browser history navigation (popstate re-reads the URL into the filters).
  // Seeded with the initial value so this is a no-op on first run (mount already loads it).
  let lastLoadedGroup = tableFilters.filters.mem_group.trim();
  $effect(() => {
    const group = tableFilters.filters.mem_group.trim();
    if (group === lastLoadedGroup) return;
    lastLoadedGroup = group;
    void loadMemories();
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

  async function loadMemories() {
    memoriesError = '';
    memoriesLoading = true;
    try {
      // Scope to the selected partition when one is chosen; '' loads the page default.
      const r = await loadMemoriesList(tableFilters.filters.mem_group.trim() || undefined);
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
   * used by filters. The page owns the entity-graph model + its SSE subscription.
   */
  function mount(): void {
    void loadMemories();
    void loadMemoryGroups();
    void loadChatChannels();
    void loadCharacters();
  }

  return {
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
      return provenance.row;
    },
    get memoryProvenanceChunks() {
      return provenance.chunks;
    },
    get memoryProvenanceLoading() {
      return provenance.loading;
    },
    get memoryProvenanceError() {
      return provenance.error;
    },
    get clearMemoriesConfirmOpen() {
      return clearMemoriesConfirmOpen;
    },
    // URL-synced filter values (read) + single write path; column sort controller.
    get filters() {
      return tableFilters.filters;
    },
    setFilter,
    sort,
    mount,
    loadMemories,
    refreshMemories: loadMemories,
    closeMemoryJsonDialog,
    closeClearMemoriesDialog,
    requestClearMemoriesConfirm,
    showMemoryJsonRow,
    showMemoryProvenance: provenance.open,
    closeMemoryProvenance: provenance.close,
    confirmClearMemories
  };
}

export type MemoriesPageController = ReturnType<typeof createMemoriesPageController>;
