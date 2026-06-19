import {
  listKnowledgeGraphEpisodes,
  searchGraphChunks,
  type GraphEpisode
} from '$lib/api/knowledge';
import { SEARCH_DEBOUNCE_MS } from './graph-types';
import { readEpisodeSel, writeEpisodeSel } from './graph-persistence';

export function createGraphSearch(deps: {
  getActiveGroupId: () => string | null;
}) {
  let searchQuery = $state('');
  let matchedChunkIds = $state<Set<string>>(new Set());
  let episodes = $state<GraphEpisode[]>([]);
  let episodesBusy = $state(false);
  let episodeChunkIds = $state<Set<string>>(new Set());
  let searchBusy = $state(false);
  let searchAbort: AbortController | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleChunkSearch(term: string): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchAbort?.abort();
    searchAbort = null;
    if (!term) {
      searchBusy = false;
      return;
    }
    searchBusy = true;
    searchTimer = setTimeout(() => {
      const ctrl = new AbortController();
      searchAbort = ctrl;
      void (async () => {
        try {
          const res = await searchGraphChunks(term, ctrl.signal);
          if (ctrl.signal.aborted) return;
          matchedChunkIds = new Set(res.data?.point_ids ?? []);
        } catch (err) {
          if (ctrl.signal.aborted) return;
          console.error('graph chunk-text search failed', err);
          matchedChunkIds = new Set();
        } finally {
          if (!ctrl.signal.aborted) searchBusy = false;
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
  }

  function search(query: string): void {
    searchQuery = query;
    if (!query.trim()) matchedChunkIds = new Set();
    scheduleChunkSearch(query.trim());
  }

  function clearSearch(): void {
    search('');
  }

  function teardownSearch(): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = null;
    searchAbort?.abort();
    searchAbort = null;
    searchBusy = false;
  }

  async function loadEpisodes(): Promise<void> {
    const gid = deps.getActiveGroupId();
    if (!gid) {
      episodes = [];
      return;
    }
    episodesBusy = true;
    try {
      const res = await listKnowledgeGraphEpisodes(gid);
      episodes = res.ok && res.data ? res.data.episodes : [];
      const present = new Set(episodes.map((e) => e.id));
      const restored = readEpisodeSel(gid).filter((id) => present.has(id));
      episodeChunkIds = new Set(restored);
    } catch (err) {
      console.error('graph: failed to load episodes', err);
      episodes = [];
    } finally {
      episodesBusy = false;
    }
  }

  function setSelectedEpisodes(ids: string[]): void {
    episodeChunkIds = new Set(ids);
    const gid = deps.getActiveGroupId();
    if (gid) writeEpisodeSel(gid, ids);
  }

  function clearEpisodes(): void {
    setSelectedEpisodes([]);
  }

  function resetEpisodesOnGroupChange(): void {
    episodeChunkIds = new Set();
  }

  const searchActive = $derived(searchQuery.trim().length > 0 || episodeChunkIds.size > 0);

  return {
    get searchQuery() {
      return searchQuery;
    },
    get matchedChunkIds() {
      return matchedChunkIds;
    },
    get episodes() {
      return episodes;
    },
    get episodesBusy() {
      return episodesBusy;
    },
    get episodeChunkIds() {
      return episodeChunkIds;
    },
    get searchBusy() {
      return searchBusy;
    },
    get searchActive() {
      return searchActive;
    },
    search,
    clearSearch,
    teardownSearch,
    loadEpisodes,
    setSelectedEpisodes,
    clearEpisodes,
    resetEpisodesOnGroupChange
  };
}

export type GraphSearch = ReturnType<typeof createGraphSearch>;
