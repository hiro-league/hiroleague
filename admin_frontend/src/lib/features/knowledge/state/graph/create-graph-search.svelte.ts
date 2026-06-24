import {
  listKnowledgeGraphEpisodes,
  searchGraphChunks,
  type GraphEpisode
} from '$lib/api/knowledge';
import { createTextSearch } from '$lib/search/create-text-search.svelte';
import { SEARCH_DEBOUNCE_MS } from './graph-types';
import { readEpisodeSel, writeEpisodeSel } from './graph-persistence';

export function createGraphSearch(deps: {
  getActiveGroupId: () => string | null;
}) {
  let matchedChunkIds = $state<Set<string>>(new Set());
  let episodes = $state<GraphEpisode[]>([]);
  let episodesBusy = $state(false);
  let episodeChunkIds = $state<Set<string>>(new Set());
  let searchBusy = $state(false);
  let searchAbort: AbortController | null = null;

  function clearChunkMatches(): void {
    searchAbort?.abort();
    searchAbort = null;
    matchedChunkIds = new Set();
    searchBusy = false;
  }

  async function runChunkSearch(term: string): Promise<void> {
    searchAbort?.abort();
    const ctrl = new AbortController();
    searchAbort = ctrl;
    searchBusy = true;
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
  }

  const textSearch = createTextSearch({
    debounceMs: SEARCH_DEBOUNCE_MS,
    onCommit: (q) => {
      const term = q.trim();
      if (!term) {
        clearChunkMatches();
        return;
      }
      void runChunkSearch(term);
    }
  });

  function search(query: string): void {
    if (!query.trim()) clearChunkMatches();
    textSearch.set(query);
  }

  function clearSearch(): void {
    textSearch.clear();
  }

  function teardownSearch(): void {
    textSearch.teardown();
    clearChunkMatches();
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

  const searchActive = $derived(textSearch.query.trim().length > 0 || episodeChunkIds.size > 0);

  return {
    get searchQuery() {
      return textSearch.query;
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
