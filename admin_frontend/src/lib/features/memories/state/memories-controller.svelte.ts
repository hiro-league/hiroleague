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
import { preserveStickyAnchorAround } from '$lib/components/page/table/preserve-sticky-anchor';
import {
  memoryField,
  memoryId,
  memoryRowPassesFilters,
  memorySortSeconds
} from '$lib/features/graph-runs/graph-runs-pure';
import {
  graphRunsClearAllMemories,
  graphRunsDeleteMemories,
  graphRunsDeleteMemory,
  graphRunsLoadMemoriesList
} from '$lib/features/graph-runs/state/graph-runs-memory-service';

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
  let deleteMemoryTarget = $state<Record<string, unknown> | null>(null);

  let memorySearch = $state('');
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
      const r = await graphRunsLoadMemoriesList();
      memoryEnabled = r.memoryEnabled;
      memoriesRows = r.memories;
      memoriesError = r.error;
    } finally {
      memoriesLoading = false;
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
      // The active filters define the delete scope: no filter → wipe everything (efficient
      // group clear, also removes the episodes); any filter → delete exactly the shown rows
      // (per-character / source / search) by edge id.
      const filtered =
        memoryFilterCharacterId.trim() !== '' ||
        memoryFilterSource.trim() !== '' ||
        memoryFilterDateFrom.trim() !== '' ||
        memoryFilterDateTo.trim() !== '' ||
        memorySearchNeedle !== '';
      if (filtered) {
        const ids = visibleMemoriesRows.map((row) => memoryId(row)).filter(Boolean);
        await graphRunsDeleteMemories(ids);
      } else {
        await graphRunsClearAllMemories();
      }
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

  /** Call from page `onMount` — loads memories and the character/channel lookups used by filters. */
  function mount(): void {
    void loadMemories();
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
    get clearMemoriesConfirmOpen() {
      return clearMemoriesConfirmOpen;
    },
    get deleteMemoryTarget() {
      return deleteMemoryTarget;
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
    openDeleteMemoryDialog,
    closeDeleteMemoryDialog,
    closeClearMemoriesDialog,
    requestClearMemoriesConfirm,
    showMemoryJsonRow,
    confirmClearMemories,
    confirmDeleteMemory
  };
}

export type MemoriesPageController = ReturnType<typeof createMemoriesPageController>;
