/**
 * Knowledge Graph tab controller (graph viz MVP).
 *
 * Holds the in-memory graph (nodes/edges) for the force-directed view and
 * applies live `knowledge.graph.*` SSE deltas. The EventSource lifecycle is
 * owned by KnowledgeGraphPanel (connect on mount, disconnect on destroy) so it
 * only runs while the Graph tab is open.
 *
 * Strategy (see docs/knowledge-graph-viz-design.md):
 *  - initial paint = one full export
 *  - live upserts = incremental deltas, coalesced per animation frame so a fast
 *    ingest doesn't thrash the force simulation
 *  - `ingest_completed` = one debounced reconciling re-export (heals drops)
 *
 * Node/edge objects are mutated in place on upsert (not replaced) so force-graph
 * preserves their simulated x/y positions across "pulse" (provenance-merge) updates.
 */

import {
  clearKnowledgeGraph,
  exportKnowledgeGraph,
  listKnowledgeGraphGroups,
  searchGraphChunks,
  type GraphEdgeDTO,
  type GraphEdgeEvent,
  type GraphGroup,
  type GraphIngestProgress,
  type GraphNodeDTO,
  type GraphNodeEvent
} from '$lib/api/knowledge';
import { connectKnowledgeGraphEvents } from '../shared/knowledge-events';
import { GLOW_MS } from '../graph/engine/graph-config';
import { linkEndId } from '../graph/engine/graph-types';
import { KNOWN_NODE_TYPE_ORDER } from '../graph/knowledge-graph-style';
import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readSessionString,
  removeSessionString,
  writeSessionString
} from '$lib/preferences/storage';

export interface KnowledgeGraphModelDeps {
  setError: (msg: string | null) => void;
}

export type GraphSelection = { kind: 'node'; id: string } | { kind: 'edge'; id: string } | null;

/** One row of the node/edge type filter strip: a type, how many carry it, hidden state. */
export type GraphTypeFacet = { type: string; count: number; hidden: boolean };

// GLOW_MS (how long a freshly-created node/edge glows after appearing) is shared with the
// canvas engine via engine/graph-config so the recent[] prune window and the fade window agree.
// Debounce window for the post-ingest reconciling re-export (ms).
const RECONCILE_DEBOUNCE_MS = 400;
// Debounce window for the backend chunk-text search leg (ms).
const SEARCH_DEBOUNCE_MS = 250;

// Filter persistence: each hidden-type set is kept in sessionStorage only — no URL
// params (filters aren't meant to be shareable links), just remembered for the
// session. Comma-joined hidden-type lists; empty set clears the key.
const SESSION_HIDE_NODES = PREF_KEYS.knowledgeGraphHideNodes;
const SESSION_HIDE_EDGES = PREF_KEYS.knowledgeGraphHideEdges;
// Last-viewed partition group_id — remembered across opens (design: default = first in list,
// remember last). Restored in loadGroups() iff the group still exists.
const SESSION_ACTIVE_GROUP = PREF_KEYS.knowledgeGraphActiveGroup;

function readHidden(key: string): Set<string> {
  const raw = readSessionString(key);
  if (!raw) return new Set();
  return new Set(raw.split(',').map((s) => s.trim()).filter(Boolean));
}

function writeHidden(key: string, hidden: Set<string>): void {
  if (hidden.size > 0) writeSessionString(key, [...hidden].join(','));
  else removeSessionString(key);
}

// Sort node-type facets: known ontology types first (in canonical order), then
// any Graphiti-emitted unknown types alphabetically.
function sortNodeFacets(facets: GraphTypeFacet[]): GraphTypeFacet[] {
  const rank = (t: string) => {
    const i = KNOWN_NODE_TYPE_ORDER.indexOf(t);
    return i === -1 ? KNOWN_NODE_TYPE_ORDER.length : i;
  };
  return [...facets].sort((a, b) => rank(a.type) - rank(b.type) || a.type.localeCompare(b.type));
}

export function createKnowledgeGraphModel(deps: KnowledgeGraphModelDeps) {
  let nodes = $state<GraphNodeDTO[]>([]);
  let links = $state<GraphEdgeDTO[]>([]);
  let loading = $state(false);
  // Last load failure (timeout / network / server). Lets the panel show an actionable
  // "couldn't load — retry" warning instead of the misleading "No graph yet" empty state
  // when an export request is aborted (e.g. too many open tabs saturate the connection pool).
  let loadError = $state<string | null>(null);
  let truncated = $state(false);
  // Bumped on every full (re)export so the renderer can tell a structural reload
  // (initial load / manual reload / reconcile) apart from incremental live deltas.
  // A reload wants a fresh relayout + zoom-to-fit; live deltas should NOT re-simulate
  // and reposition the whole graph (see KnowledgeGraphPanel graphData effect).
  let loadVersion = $state(0);
  let live = $state(false);
  let progress = $state<GraphIngestProgress | null>(null);
  let selected = $state<GraphSelection>(null);
  // Group filter: the partitions present in the graph + which one is shown. We simply list
  // whatever groups exist (no privileged "knowledge is home" default) and show the selected
  // one — default = first in the list, last selection remembered (resolved in loadGroups).
  // `null` only before groups have loaded or when the graph is empty. Drives the export scope
  // and the live-event filter.
  let groups = $state<GraphGroup[]>([]);
  let activeGroupId = $state<string | null>(null);
  // id (prefixed n:/e:) -> epoch ms of last "is_new" sighting; drives the glow.
  let recent = $state<Record<string, number>>({});

  // ── View filters (client-side; the full snapshot is already in memory) ──
  // We store the HIDDEN types so the default (empty set) means "show all".
  // Reassigned with a fresh Set on every change so $state reactivity fires.
  // Seeded from the URL so a filtered view is restored on reload.
  let hiddenNodeTypes = $state<Set<string>>(readHidden(SESSION_HIDE_NODES));
  let hiddenEdgeTypes = $state<Set<string>>(readHidden(SESSION_HIDE_EDGES));

  // Non-reactive O(1) indexes — the dedup source of truth. Values are the same
  // object references held in the reactive arrays (mutated in place on upsert).
  const nodeById = new Map<string, GraphNodeDTO>();
  const edgeById = new Map<string, GraphEdgeDTO>();

  // rAF-coalesced delta buffer.
  let pendingNodes: GraphNodeEvent[] = [];
  let pendingEdges: GraphEdgeEvent[] = [];
  let flushScheduled = false;
  let reconcileTimer: ReturnType<typeof setTimeout> | null = null;

  function rebuildArrays(): void {
    nodes = [...nodeById.values()];
    // Drop dangling edges (an edge delta can arrive before its node delta) — but FIRST
    // normalize the endpoint to its id via the shared `linkEndId`. Historically the canvas
    // fed force-graph the model's edge objects, which force-graph rewrote source/target from
    // id strings into node OBJECTS; a naive `nodeById.has(e.source)` then checked has(<object>)
    // → false → every rendered edge was filtered out, collapsing the link structure and
    // re-scattering the nodes. The engine now uses its own mirror links so the model's edges
    // keep string endpoints, but linkEndId stays as cheap insurance against either shape.
    links = [...edgeById.values()].filter(
      (e) => nodeById.has(linkEndId(e.source)) && nodeById.has(linkEndId(e.target))
    );
  }

  function upsertNode(dto: GraphNodeDTO): void {
    const existing = nodeById.get(dto.id);
    if (existing) {
      Object.assign(existing, dto); // keep reference → preserve x/y
    } else {
      nodeById.set(dto.id, { ...dto });
    }
  }

  function upsertEdge(dto: GraphEdgeDTO): void {
    const existing = edgeById.get(dto.id);
    if (existing) {
      Object.assign(existing, dto);
    } else {
      edgeById.set(dto.id, { ...dto });
    }
  }

  function flush(): void {
    flushScheduled = false;
    if (pendingNodes.length === 0 && pendingEdges.length === 0) return;
    const now = Date.now();
    const nextRecent = { ...recent };
    for (const ev of pendingNodes) {
      upsertNode(ev.node);
      if (ev.is_new) nextRecent[`n:${ev.node.id}`] = now;
    }
    for (const ev of pendingEdges) {
      upsertEdge(ev.edge);
      if (ev.is_new) nextRecent[`e:${ev.edge.id}`] = now;
    }
    pendingNodes = [];
    pendingEdges = [];
    for (const key of Object.keys(nextRecent)) {
      if (now - nextRecent[key] > GLOW_MS) delete nextRecent[key];
    }
    recent = nextRecent;
    rebuildArrays();
  }

  function scheduleFlush(): void {
    if (typeof requestAnimationFrame === 'undefined') {
      flush();
      return;
    }
    if (flushScheduled) return;
    flushScheduled = true;
    requestAnimationFrame(flush);
  }

  function scheduleReconcile(): void {
    if (reconcileTimer) clearTimeout(reconcileTimer);
    reconcileTimer = setTimeout(() => {
      reconcileTimer = null;
      void load();
    }, RECONCILE_DEBOUNCE_MS);
  }

  async function load(): Promise<void> {
    loading = true;
    loadError = null;
    deps.setError(null);
    try {
      // Scope to the selected partition. null only when no group exists yet (empty graph) —
      // then the backend default applies and the canvas is simply empty.
      const res = await exportKnowledgeGraph(
        activeGroupId ? { groupIds: [activeGroupId] } : {}
      );
      if (!res.ok || !res.data) {
        loadError = res.error ?? 'Failed to load graph';
        deps.setError(loadError);
        return;
      }
      nodeById.clear();
      edgeById.clear();
      for (const n of res.data.nodes) nodeById.set(n.id, { ...n });
      for (const e of res.data.edges) edgeById.set(e.id, { ...e });
      truncated = res.data.truncated;
      recent = {};
      rebuildArrays();
      loadVersion += 1; // signal a structural reload to the renderer (full relayout + fit)
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
      deps.setError(loadError);
    } finally {
      loading = false;
    }
  }

  /** Wipe the entire knowledge graph (server clears the knowledge group). Returns true
   *  on success — the panel then reloads so the canvas reflects the now-empty graph. */
  async function clearGraph(): Promise<boolean> {
    loading = true;
    deps.setError(null);
    try {
      const res = await clearKnowledgeGraph();
      if (!res.ok) {
        deps.setError(res.error ?? 'Failed to clear graph');
        return false;
      }
      return true;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      loading = false;
    }
  }

  /** Fetch the partitions present in the graph and resolve which one to show.
   *  We list whatever groups exist (the backend enumerates DISTINCT group_ids) and pick the
   *  active one: keep the current selection if it still exists, else restore the remembered
   *  one, else default to the FIRST group in the list. `null` only when the graph is empty. */
  async function loadGroups(): Promise<void> {
    const res = await listKnowledgeGraphGroups();
    if (!res.ok || !res.data) return;
    groups = res.data.groups;
    const ids = new Set(groups.map((g) => g.id));
    if (activeGroupId && ids.has(activeGroupId)) return; // keep an explicit current selection
    const remembered = readSessionString(SESSION_ACTIVE_GROUP);
    activeGroupId = remembered && ids.has(remembered) ? remembered : (groups[0]?.id ?? null);
  }

  /** Switch the viewed partition (remembered across opens) and reload (relayout + fit). */
  async function selectGroup(id: string | null): Promise<void> {
    if (id === activeGroupId) return;
    activeGroupId = id;
    if (id) writeSessionString(SESSION_ACTIVE_GROUP, id);
    else removeSessionString(SESSION_ACTIVE_GROUP);
    await load();
  }

  // Does a live delta belong to the partition we're currently showing? Exact match on the
  // selected group_id — no privileged-default special-casing. When nothing is selected yet
  // (empty graph), deltas wait for the post-ingest reconcile (which re-lists groups).
  function eventMatchesActiveGroup(gid: string | null | undefined): boolean {
    if (activeGroupId === null) return false;
    return (gid ?? '') === activeGroupId;
  }

  function connectEvents(): () => void {
    live = true;
    const disconnect = connectKnowledgeGraphEvents({
      onNode: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        pendingNodes.push(e);
        scheduleFlush();
      },
      onEdge: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        pendingEdges.push(e);
        scheduleFlush();
      },
      onProgress: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        progress = e;
      },
      onCompleted: () => {
        progress = null;
        // Refresh the partition list too: a first ingest into an empty graph creates a new
        // group that should appear in the selector (and get auto-selected if none was).
        void loadGroups();
        scheduleReconcile();
      }
    });
    return () => {
      live = false;
      progress = null;
      if (reconcileTimer) {
        clearTimeout(reconcileTimer);
        reconcileTimer = null;
      }
      teardownSearch(); // cancel any pending/in-flight chunk-text search
      disconnect();
    };
  }

  function selectNode(id: string): void {
    selected = { kind: 'node', id };
  }
  function selectEdge(id: string): void {
    selected = { kind: 'edge', id };
  }
  function clearSelection(): void {
    selected = null;
  }

  function selectedNode(): GraphNodeDTO | null {
    return selected?.kind === 'node' ? (nodeById.get(selected.id) ?? null) : null;
  }
  function selectedEdge(): GraphEdgeDTO | null {
    return selected?.kind === 'edge' ? (edgeById.get(selected.id) ?? null) : null;
  }
  function nodeName(id: string): string {
    return nodeById.get(id)?.name ?? id;
  }

  // Resolve a link endpoint to its node type. force-graph mutates link.source/
  // target from id strings into node-object references once the graph is laid
  // out, so accept either shape.
  function endpointType(end: unknown): string | undefined {
    if (end && typeof end === 'object') return (end as GraphNodeDTO).type;
    return typeof end === 'string' ? nodeById.get(end)?.type : undefined;
  }

  // An edge is visible only if its relation type is shown AND both endpoints'
  // node types are shown — hiding a node type also hides edges touching it
  // ("hide connected edges" semantics).
  function isEdgeVisible(edge: GraphEdgeDTO): boolean {
    if (hiddenEdgeTypes.has(edge.rel_type)) return false;
    const st = endpointType(edge.source);
    const tt = endpointType(edge.target);
    if (st && hiddenNodeTypes.has(st)) return false;
    if (tt && hiddenNodeTypes.has(tt)) return false;
    return true;
  }
  function isNodeVisible(node: GraphNodeDTO): boolean {
    return !hiddenNodeTypes.has(node.type);
  }

  // Facets reflect ALL loaded data (not the filtered subset) so hidden types
  // stay listed and can be toggled back on.
  const nodeTypeFacets = $derived.by<GraphTypeFacet[]>(() => {
    const counts = new Map<string, number>();
    for (const n of nodes) counts.set(n.type, (counts.get(n.type) ?? 0) + 1);
    return sortNodeFacets(
      [...counts].map(([type, count]) => ({ type, count, hidden: hiddenNodeTypes.has(type) }))
    );
  });
  const edgeTypeFacets = $derived.by<GraphTypeFacet[]>(() => {
    const counts = new Map<string, number>();
    for (const e of links) counts.set(e.rel_type, (counts.get(e.rel_type) ?? 0) + 1);
    // Busiest relations first, then alphabetical.
    return [...counts]
      .map(([type, count]) => ({ type, count, hidden: hiddenEdgeTypes.has(type) }))
      .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
  });

  // The filtered subsets fed to the force-graph instance. Filtering rebuilds the
  // graph from these (recreate + re-layout) rather than hiding in place, so the
  // remaining nodes spread to fill the frame. visibleLinks is derived from the
  // already-non-dangling `links`, and isEdgeVisible drops any edge whose endpoint
  // type is hidden, so every visible edge's endpoints are in visibleNodes.
  const visibleNodes = $derived(nodes.filter(isNodeVisible));
  const visibleLinks = $derived(links.filter(isEdgeVisible));
  const visibleNodeCount = $derived(visibleNodes.length);
  const visibleEdgeCount = $derived(visibleLinks.length);
  const hasActiveFilters = $derived(hiddenNodeTypes.size > 0 || hiddenEdgeTypes.size > 0);

  // ── Search highlight (transient view state; not persisted) ──────────────────
  // One unified query highlights matching nodes/edges WITHOUT hiding the rest:
  //   • node name/aliases + edge rel_type/fact → matched here (client-side, instant)
  //   • chunk TEXT → matched via a debounced backend lookup (searchGraphChunks returns
  //     point_ids == chunk_ids); we map them onto nodes/edges by chunk_ids. Union below.
  // The query IS the input value (the Graph toolbar binds to searchQuery()), so search
  // state survives a tab switch — there's no panel-local copy to fall out of sync.
  let searchQuery = $state('');
  // Qdrant point_ids whose chunk text matched the current query (== chunk_ids); cleared
  // when the query clears so a stale chunk match never outlives its text.
  let matchedChunkIds = $state<Set<string>>(new Set());
  // True while the debounced backend chunk-text leg is in flight (drives the spinner).
  let searchBusy = $state(false);
  let searchAbort: AbortController | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  // Debounced backend chunk-TEXT search. searchGraphChunks THROWS on error/abort, so the
  // rejection must be caught or searchBusy sticks on. Aborted on a newer keystroke / clear.
  function scheduleChunkSearch(term: string): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchAbort?.abort(); // a newer keystroke supersedes the in-flight lookup
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
          if (ctrl.signal.aborted) return; // expected on a newer keystroke / teardown
          console.error('graph chunk-text search failed', err);
          matchedChunkIds = new Set(); // fall back to client-only (name/rel) matches
        } finally {
          if (!ctrl.signal.aborted) searchBusy = false;
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
  }

  // Drive the unified search: instant client-side name/alias + rel_type/fact highlight
  // (via searchQuery), plus the debounced backend chunk-text leg.
  function search(query: string): void {
    searchQuery = query;
    if (!query.trim()) matchedChunkIds = new Set(); // clearing the box clears chunk matches too
    scheduleChunkSearch(query.trim());
  }
  function clearSearch(): void {
    search('');
  }
  // Cancel any pending/in-flight chunk search (called on page teardown).
  function teardownSearch(): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = null;
    searchAbort?.abort();
    searchAbort = null;
    searchBusy = false;
  }

  const searchActive = $derived(searchQuery.trim().length > 0);

  // Nodes matched by the query: name/alias substring, OR any chunk_id in matchedChunkIds.
  const matchedNodeIds = $derived.by<Set<string>>(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return new Set();
    const out = new Set<string>();
    for (const n of nodes) {
      if (
        n.name.toLowerCase().includes(q) ||
        n.aliases.some((a) => a.toLowerCase().includes(q)) ||
        n.chunk_ids.some((c) => matchedChunkIds.has(c))
      ) {
        out.add(n.id);
      }
    }
    return out;
  });
  // Edges matched by the query: rel_type/fact substring, OR any chunk_id in matchedChunkIds.
  const matchedEdgeIds = $derived.by<Set<string>>(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return new Set();
    const out = new Set<string>();
    for (const e of links) {
      if (
        e.rel_type.toLowerCase().includes(q) ||
        (e.fact ?? '').toLowerCase().includes(q) ||
        e.chunk_ids.some((c) => matchedChunkIds.has(c))
      ) {
        out.add(e.id);
      }
    }
    return out;
  });
  const matchCount = $derived(matchedNodeIds.size + matchedEdgeIds.size);

  function toggleNodeType(type: string): void {
    const next = new Set(hiddenNodeTypes);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    hiddenNodeTypes = next;
    writeHidden(SESSION_HIDE_NODES, next);
  }
  // Edge types are filtered via the multi-select dropdown, which works in terms
  // of VISIBLE (checked) types: hidden = (all present edge types) − visible.
  function setVisibleEdgeTypes(visible: string[]): void {
    const shown = new Set(visible);
    const next = new Set<string>();
    for (const e of links) {
      if (!shown.has(e.rel_type)) next.add(e.rel_type);
    }
    hiddenEdgeTypes = next;
    writeHidden(SESSION_HIDE_EDGES, next);
  }
  function clearFilters(): void {
    hiddenNodeTypes = new Set();
    hiddenEdgeTypes = new Set();
    writeHidden(SESSION_HIDE_NODES, hiddenNodeTypes);
    writeHidden(SESSION_HIDE_EDGES, hiddenEdgeTypes);
  }

  return {
    nodes: () => nodes,
    links: () => links,
    loading: () => loading,
    loadError: () => loadError,
    loadVersion: () => loadVersion,
    truncated: () => truncated,
    live: () => live,
    progress: () => progress,
    recent: () => recent,
    selected: () => selected,
    selectedNode,
    selectedEdge,
    nodeName,
    selectNode,
    selectEdge,
    clearSelection,
    load,
    clearGraph,
    connectEvents,
    // ── group filter ──
    groups: () => groups,
    activeGroupId: () => activeGroupId,
    loadGroups,
    selectGroup,
    // ── view filters ──
    nodeTypeFacets: () => nodeTypeFacets,
    edgeTypeFacets: () => edgeTypeFacets,
    hiddenNodeTypes: () => hiddenNodeTypes,
    hiddenEdgeTypes: () => hiddenEdgeTypes,
    visibleNodes: () => visibleNodes,
    visibleLinks: () => visibleLinks,
    visibleNodeCount: () => visibleNodeCount,
    visibleEdgeCount: () => visibleEdgeCount,
    hasActiveFilters: () => hasActiveFilters,
    toggleNodeType,
    setVisibleEdgeTypes,
    clearFilters,
    // ── search highlight ──
    searchQuery: () => searchQuery,
    searchBusy: () => searchBusy,
    search,
    clearSearch,
    searchActive: () => searchActive,
    matchedNodeIds: () => matchedNodeIds,
    matchedEdgeIds: () => matchedEdgeIds,
    matchCount: () => matchCount
  };
}

export type KnowledgeGraphModel = ReturnType<typeof createKnowledgeGraphModel>;
