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
  memoryKind,
  memoryRowPassesFilters,
  memorySourceOptions,
  sortMemories,
  type MemoryFilterKey,
  type MemorySortColumn
} from '../shared/memory-pure';
import { clearGroup, deleteMemories, loadMemoriesList } from './memories-service';
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
  let clearGroupConfirmOpen = $state(false);

  // Provenance drill-down (originating conversation turn(s) for a fact) is its own module.
  const provenance = createMemoryProvenance();

  // Group filter (server-side): a single group is ALWAYS selected — a group id = that one
  // partition's facts (memory / knowledge / eval). There is no "all groups" scope anymore
  // (it was confusing: "all" only ever meant conversation-memory groups, never knowledge/eval).
  // Unlike the other filters (client-side over the loaded rows), changing this RELOADS the list.
  // Options are sourced from the same /knowledge/graph/groups endpoint the Graph tab uses.
  let memoryGroups = $state<GraphGroup[]>([]);
  // The backend's suggested default partition (from /knowledge/graph/groups) — used only as a
  // fallback when the workspace has no conversation-memory group to land on.
  let memoryDefaultGroupId = $state<string | null>(null);

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

  // The group to land on when none is selected: the first conversation-memory group (this is a
  // Memories page), else the backend's suggested default, else the first group of any kind.
  const defaultMemoryGroupId = $derived.by((): string => {
    const mem = memoryGroups.find((g) => g.kind === 'memory');
    if (mem) return mem.id;
    const backendDefault = (memoryDefaultGroupId ?? '').trim();
    if (backendDefault && memoryGroups.some((g) => g.id === backendDefault)) return backendDefault;
    return memoryGroups[0]?.id ?? '';
  });

  // Logical label of the selected group — for the "Clear group" dialog copy.
  const selectedGroupLabel = $derived.by((): string => {
    const gid = tableFilters.filters.mem_group.trim();
    return memoryGroupLabelById.get(gid) || gid;
  });

  // True when a ROW-LEVEL filter is narrowing the view. The group is now the base scope (always
  // set), NOT a filter — so it's excluded here. Governs whether "Clear memories" is offered.
  const memoryRowFiltersActive = $derived(
    tableFilters.filters.mem_char.trim() !== '' ||
      tableFilters.filters.mem_source.trim() !== '' ||
      tableFilters.filters.mem_from.trim() !== '' ||
      tableFilters.filters.mem_to.trim() !== '' ||
      memorySearchQuery.trim() !== ''
  );

  // "Clear memories" deletes only the shown RELATION facts (edge ids). Entity/summary rows are
  // excluded for now (their delete semantics are undecided) — use "Clear group" to wipe those.
  const clearableMemoryIds = $derived.by((): string[] =>
    visibleMemoriesRows
      .filter((row) => memoryKind(row) === 'relation')
      .map((row) => memoryId(row))
      .filter(Boolean)
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

  // Row-level narrowing keys (everything except the base group scope). Clearing these also
  // drops them from the URL (useTableFilters deletes empty params).
  const MEMORY_ROW_FILTER_KEYS: MemoryFilterKey[] = [
    'mem_char',
    'mem_source',
    'mem_from',
    'mem_to',
    'mem_q'
  ];

  // Drop any active row filters. Called when the base group scope changes out from under them
  // (e.g. after a Clear group jumps to a new partition) so stale narrowing from the OLD group
  // can't hide every row of the new one — which read as "the clear wiped everything".
  function resetRowFilters() {
    for (const key of MEMORY_ROW_FILTER_KEYS) {
      if (tableFilters.filters[key].trim()) setFilter(key, '');
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
    try {
      const data = (await listKnowledgeGraphGroups()).data;
      memoryGroups = data.groups;
      memoryDefaultGroupId = data.default_group_id;
    } catch {
      // Non-fatal — the selector stays with whatever group was last loaded.
    }
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

  function requestClearGroupConfirm() {
    clearGroupConfirmOpen = true;
  }

  function closeClearGroupDialog() {
    if (!memoryActionBusy) clearGroupConfirmOpen = false;
  }

  function showMemoryJsonRow(row: Record<string, unknown>) {
    memoryJsonRow = row;
  }

  // "Clear memories": delete exactly the shown RELATION facts by edge id. Entity/summary rows
  // are excluded (see clearableMemoryIds) — those go through "Clear group".
  async function confirmClearMemories() {
    memoryActionBusy = true;
    memoriesError = '';
    try {
      await deleteMemories(clearableMemoryIds);
      clearMemoriesConfirmOpen = false;
      await loadMemories();
    } catch (e) {
      memoriesError = e instanceof Error ? e.message : 'Failed to clear memories.';
    } finally {
      memoryActionBusy = false;
    }
  }

  // "Clear group": wipe the whole selected partition (facts + entities + episodes +
  // communities). The group then disappears from the selector, so re-seed to a new default.
  async function confirmClearGroup() {
    const gid = tableFilters.filters.mem_group.trim();
    if (!gid) {
      clearGroupConfirmOpen = false;
      return;
    }
    memoryActionBusy = true;
    memoriesError = '';
    try {
      await clearGroup(gid);
      clearGroupConfirmOpen = false;
      await loadMemoryGroups();
      // Stale row filters belonged to the wiped group — drop them so they don't hide the next
      // group's rows (which looked like "the clear emptied everything").
      resetRowFilters();
      // The cleared group is gone (its episodes were deleted). Land on a fresh default;
      // if one is still selectable, changing it reloads via the group-scope effect.
      const next = defaultMemoryGroupId;
      if (next && next !== gid) {
        setFilter('mem_group', next);
      } else {
        await loadMemories();
      }
    } catch (e) {
      memoriesError = e instanceof Error ? e.message : 'Failed to clear group.';
    } finally {
      memoryActionBusy = false;
    }
  }

  /**
   * Call from page `onMount` — loads memories and the character/channel lookups
   * used by filters. The page owns the entity-graph model + its SSE subscription.
   */
  function mount(): void {
    void initGroupsThenLoad();
    void loadChatChannels();
    void loadCharacters();
  }

  // A single group is always selected now. Load the group list first, then land on a group
  // (respecting a deep-linked ?mem_group=), and only then load its memories — so we never do the
  // wasteful "all groups" fetch the old empty-scope default triggered.
  async function initGroupsThenLoad(): Promise<void> {
    await loadMemoryGroups();
    const current = tableFilters.filters.mem_group.trim();
    // A group in the URL that no longer exists (e.g. it was just cleared, then the page was
    // refreshed) must NOT be loaded as-is — it would read empty forever. Fall back to the
    // default and drop the old group's stale row filters.
    const known = current !== '' && memoryGroups.some((g) => g.id === current);
    const def = defaultMemoryGroupId;
    if (!known && def) {
      if (current) resetRowFilters();
      setFilter('mem_group', def); // group-scope effect reloads the list for the new group
    } else {
      await loadMemories(); // valid deep-linked group, or no groups at all → load (scoped / fallback)
    }
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
    get clearGroupConfirmOpen() {
      return clearGroupConfirmOpen;
    },
    // "Clear memories" is offered only when a row-level filter is active AND there are relation
    // facts in view to delete (entities are excluded from this action).
    get canClearMemories() {
      return memoryRowFiltersActive && clearableMemoryIds.length > 0;
    },
    get clearableMemoryCount() {
      return clearableMemoryIds.length;
    },
    get selectedGroupLabel() {
      return selectedGroupLabel;
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
    requestClearGroupConfirm,
    closeClearGroupDialog,
    confirmClearGroup,
    showMemoryJsonRow,
    showMemoryProvenance: provenance.open,
    closeMemoryProvenance: provenance.close,
    confirmClearMemories
  };
}

export type MemoriesPageController = ReturnType<typeof createMemoriesPageController>;
