import { linkEndId } from '../../graph/engine/graph-types';
import type { GraphDataStore } from './create-graph-data.svelte';
import type { GraphEdgeFilters } from './create-graph-edge-filters.svelte';
import type { GraphSearch } from './create-graph-search.svelte';
import { createGraphDataStore } from './create-graph-data.svelte';
import { createGraphEdgeFilters } from './create-graph-edge-filters.svelte';
import { createGraphGroups } from './create-graph-groups.svelte';
import { createGraphSearch } from './create-graph-search.svelte';
import { createGraphViewFilters } from './create-graph-view-filters.svelte';
import {
  buildFilterToken,
  computeCappedEdgeIds,
  computeEdgeTypeFacets,
  computeEpisodeItemCounts,
  computeLowConnCount,
  computeLowConnDimIds,
  computeMatchedEdgeIds,
  computeMatchedNodeIds,
  computeNodeInstanceFacets,
  computeVisibleDegree,
  edgeFiltersActive,
  isEdgeVisible,
  isNodeVisible,
  lowConnPass,
  maxMapValue,
  spanOf
} from './graph-filter-pure';
import {
  MAX_CONN_PER_NODE_CAP,
  type DateRange,
  type EdgeValidity,
  type LowConnTreatment,
  type MaxConnBy
} from './graph-types';

export interface KnowledgeGraphModelDeps {
  setError: (msg: string | null) => void;
}

export function createKnowledgeGraphModel(deps: KnowledgeGraphModelDeps) {
  const viewFilters = createGraphViewFilters();

  let search: GraphSearch;
  let data: GraphDataStore;
  let edgeFilters: GraphEdgeFilters;

  const groups = createGraphGroups({
    onGroupChanged: async () => {
      search.resetEpisodesOnGroupChange();
      await data.load();
    }
  });

  search = createGraphSearch({ getActiveGroupId: () => groups.activeGroupId });

  data = createGraphDataStore({
    setError: deps.setError,
    getActiveGroupId: () => groups.activeGroupId,
    eventMatchesActiveGroup: (gid) => groups.eventMatchesActiveGroup(gid),
    onLoadComplete: () => {
      edgeFilters.resetDateRangesOnLoad();
      void search.loadEpisodes();
    },
    onTeardownSearch: () => search.teardownSearch(),
    refreshGroups: () => groups.loadGroups()
  });

  const validAtSpan = $derived(spanOf(data.links, 'valid_at'));
  const createdAtSpan = $derived(spanOf(data.links, 'created_at'));

  edgeFilters = createGraphEdgeFilters({
    getValidAtSpan: () => validAtSpan,
    getCreatedAtSpan: () => createdAtSpan
  });

  const nodeInstanceFacets = $derived.by(() =>
    computeNodeInstanceFacets(data.nodes, data.links, viewFilters.hiddenNodeIds)
  );

  const edgeTypeFacets = $derived.by(() =>
    computeEdgeTypeFacets(data.links, viewFilters.hiddenEdgeTypes)
  );

  const baseVisibleLinks = $derived.by(() =>
    data.links.filter((e) =>
      isEdgeVisible(e, {
        hiddenEdgeTypes: viewFilters.hiddenEdgeTypes,
        hiddenNodeIds: viewFilters.hiddenNodeIds,
        edgeValidity: edgeFilters.edgeValidity,
        includeUndatedEdges: edgeFilters.includeUndatedEdges,
        validRange: edgeFilters.validRange,
        creationRange: edgeFilters.creationRange
      })
    )
  );

  const cappedEdgeIds = $derived.by(() =>
    computeCappedEdgeIds(baseVisibleLinks, edgeFilters.maxConnPerNode, edgeFilters.maxConnBy)
  );

  const edgeFilteredLinks = $derived(
    cappedEdgeIds ? baseVisibleLinks.filter((e) => cappedEdgeIds.has(e.id)) : baseVisibleLinks
  );

  const visibleDegree = $derived.by(() => computeVisibleDegree(edgeFilteredLinks));

  const maxVisibleDegree = $derived.by(() => maxMapValue(visibleDegree));

  const visibleNodes = $derived(
    data.nodes.filter(
      (n) =>
        isNodeVisible(n, viewFilters.hiddenNodeIds) &&
        lowConnPass(n.id, edgeFilters.lowConnTreatment, edgeFilters.lowConnThreshold, visibleDegree)
    )
  );

  const lowConnDimIds = $derived.by(() =>
    computeLowConnDimIds(
      visibleNodes,
      edgeFilters.lowConnTreatment,
      edgeFilters.lowConnThreshold,
      visibleDegree
    )
  );

  const lowConnCount = $derived.by(() =>
    computeLowConnCount(
      data.nodes,
      viewFilters.hiddenNodeIds,
      edgeFilters.lowConnThreshold,
      visibleDegree
    )
  );

  const visibleNodeIdSet = $derived(new Set(visibleNodes.map((n) => n.id)));

  const visibleLinks = $derived(
    edgeFilteredLinks.filter(
      (e) =>
        visibleNodeIdSet.has(linkEndId(e.source)) && visibleNodeIdSet.has(linkEndId(e.target))
    )
  );

  const visibleNodeCount = $derived(visibleNodes.length);
  const visibleEdgeCount = $derived(visibleLinks.length);

  const edgeFiltersActiveFlag = $derived(
    edgeFiltersActive({
      edgeValidity: edgeFilters.edgeValidity,
      validRange: edgeFilters.validRange,
      creationRange: edgeFilters.creationRange,
      maxConnPerNode: edgeFilters.maxConnPerNode,
      lowConnThreshold: edgeFilters.lowConnThreshold
    })
  );

  const hasActiveFilters = $derived(
    viewFilters.hiddenNodeIds.size > 0 ||
      viewFilters.hiddenEdgeTypes.size > 0 ||
      edgeFiltersActiveFlag
  );

  const filterToken = $derived(
    buildFilterToken({
      edgeValidity: edgeFilters.edgeValidity,
      includeUndatedEdges: edgeFilters.includeUndatedEdges,
      maxConnPerNode: edgeFilters.maxConnPerNode,
      maxConnBy: edgeFilters.maxConnBy,
      lowConnTreatment: edgeFilters.lowConnTreatment,
      lowConnThreshold: edgeFilters.lowConnThreshold,
      validRange: edgeFilters.validRange,
      creationRange: edgeFilters.creationRange
    })
  );

  const matchContext = $derived({
    searchQuery: search.searchQuery,
    matchedChunkIds: search.matchedChunkIds,
    episodeChunkIds: search.episodeChunkIds
  });

  const matchedNodeIds = $derived.by(() => computeMatchedNodeIds(data.nodes, matchContext));

  const matchedEdgeIds = $derived.by(() => computeMatchedEdgeIds(data.links, matchContext));

  const matchCount = $derived(matchedNodeIds.size + matchedEdgeIds.size);

  const episodeItemCounts = $derived.by(() => computeEpisodeItemCounts(data.nodes, data.links));

  function setVisibleNodeIds(type: string, visible: string[]): void {
    viewFilters.setVisibleNodeIds(type, visible, data.nodes);
  }

  function setVisibleEdgeTypes(visible: string[]): void {
    viewFilters.setVisibleEdgeTypes(visible, data.links);
  }

  function clearFilters(): void {
    viewFilters.clearViewFilters();
    edgeFilters.resetEdgeFilters();
  }

  return {
    nodes: () => data.nodes,
    links: () => data.links,
    loading: () => data.loading,
    loadError: () => data.loadError,
    loadVersion: () => data.loadVersion,
    truncated: () => data.truncated,
    live: () => data.live,
    progress: () => data.progress,
    recent: () => data.recent,
    selected: () => data.selected,
    selectedNode: () => data.selectedNode(),
    selectedEdge: () => data.selectedEdge(),
    nodeName: (id: string) => data.nodeName(id),
    selectNode: (id: string) => data.selectNode(id),
    selectEdge: (id: string) => data.selectEdge(id),
    clearSelection: () => data.clearSelection(),
    load: () => data.load(),
    loadPreferences: () => data.loadPreferences(),
    connectEvents: () => data.connectEvents(),
    groups: () => groups.groups,
    activeGroupId: () => groups.activeGroupId,
    loadGroups: () => groups.loadGroups(),
    selectGroup: (id: string | null) => groups.selectGroup(id),
    nodeInstanceFacets: () => nodeInstanceFacets,
    edgeTypeFacets: () => edgeTypeFacets,
    largeTypeThreshold: () => data.largeTypeThreshold,
    hiddenNodeIds: () => viewFilters.hiddenNodeIds,
    hiddenEdgeTypes: () => viewFilters.hiddenEdgeTypes,
    visibleNodes: () => visibleNodes,
    visibleLinks: () => visibleLinks,
    visibleNodeCount: () => visibleNodeCount,
    visibleEdgeCount: () => visibleEdgeCount,
    hasActiveFilters: () => hasActiveFilters,
    setVisibleNodeIds,
    setVisibleEdgeTypes,
    clearFilters,
    filterToken: () => filterToken,
    edgeValidity: () => edgeFilters.edgeValidity,
    includeUndatedEdges: () => edgeFilters.includeUndatedEdges,
    maxConnPerNode: () => edgeFilters.maxConnPerNode,
    maxConnBy: () => edgeFilters.maxConnBy,
    visibleEdgesPerPair: () => edgeFilters.visibleEdgesPerPair,
    lowConnTreatment: () => edgeFilters.lowConnTreatment,
    lowConnThreshold: () => edgeFilters.lowConnThreshold,
    lowConnDimIds: () => lowConnDimIds,
    lowConnCount: () => lowConnCount,
    maxVisibleDegree: () => maxVisibleDegree,
    validRange: () => edgeFilters.validRange,
    creationRange: () => edgeFilters.creationRange,
    validAtSpan: () => validAtSpan,
    createdAtSpan: () => createdAtSpan,
    setEdgeValidity: (v: EdgeValidity) => edgeFilters.setEdgeValidity(v),
    setIncludeUndatedEdges: (on: boolean) => edgeFilters.setIncludeUndatedEdges(on),
    setMaxConnPerNode: (n: number) => edgeFilters.setMaxConnPerNode(n),
    setMaxConnBy: (by: MaxConnBy) => edgeFilters.setMaxConnBy(by),
    setVisibleEdgesPerPair: (n: number) => edgeFilters.setVisibleEdgesPerPair(n),
    setLowConnTreatment: (t: LowConnTreatment) => edgeFilters.setLowConnTreatment(t),
    setLowConnThreshold: (n: number) => edgeFilters.setLowConnThreshold(n),
    setValidRange: (range: DateRange) => edgeFilters.setValidRange(range),
    setCreationRange: (range: DateRange) => edgeFilters.setCreationRange(range),
    resetEdgeFilters: () => edgeFilters.resetEdgeFilters(),
    searchQuery: () => search.searchQuery,
    searchBusy: () => search.searchBusy,
    search: (query: string) => search.search(query),
    clearSearch: () => search.clearSearch(),
    searchActive: () => search.searchActive,
    matchedNodeIds: () => matchedNodeIds,
    matchedEdgeIds: () => matchedEdgeIds,
    matchCount: () => matchCount,
    episodes: () => search.episodes,
    episodesBusy: () => search.episodesBusy,
    episodeItemCount: (id: string) => episodeItemCounts.get(id) ?? 0,
    selectedEpisodeIds: () => [...search.episodeChunkIds],
    setSelectedEpisodes: (ids: string[]) => search.setSelectedEpisodes(ids),
    clearEpisodes: () => search.clearEpisodes()
  };
}

export type KnowledgeGraphModel = ReturnType<typeof createKnowledgeGraphModel>;
