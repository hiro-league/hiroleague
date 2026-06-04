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
  exportKnowledgeGraph,
  type GraphEdgeDTO,
  type GraphEdgeEvent,
  type GraphIngestProgress,
  type GraphNodeDTO,
  type GraphNodeEvent
} from '$lib/api/knowledge';
import { connectKnowledgeGraphEvents } from '../shared/knowledge-events';
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

// How long a freshly-created node/edge glows after appearing (ms).
const GLOW_MS = 3000;
// Debounce window for the post-ingest reconciling re-export (ms).
const RECONCILE_DEBOUNCE_MS = 400;

// Filter persistence: each hidden-type set is kept in sessionStorage only — no URL
// params (filters aren't meant to be shareable links), just remembered for the
// session. Comma-joined hidden-type lists; empty set clears the key.
const SESSION_HIDE_NODES = PREF_KEYS.knowledgeGraphHideNodes;
const SESSION_HIDE_EDGES = PREF_KEYS.knowledgeGraphHideEdges;

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
  let truncated = $state(false);
  let live = $state(false);
  let progress = $state<GraphIngestProgress | null>(null);
  let selected = $state<GraphSelection>(null);
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
    // force-graph requires both endpoints to exist; drop dangling edges (an edge
    // delta can in principle arrive before its node delta).
    links = [...edgeById.values()].filter(
      (e) => nodeById.has(e.source) && nodeById.has(e.target)
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
    deps.setError(null);
    try {
      const res = await exportKnowledgeGraph();
      if (!res.ok || !res.data) {
        deps.setError(res.error ?? 'Failed to load graph');
        return;
      }
      nodeById.clear();
      edgeById.clear();
      for (const n of res.data.nodes) nodeById.set(n.id, { ...n });
      for (const e of res.data.edges) edgeById.set(e.id, { ...e });
      truncated = res.data.truncated;
      recent = {};
      rebuildArrays();
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : String(err));
    } finally {
      loading = false;
    }
  }

  function connectEvents(): () => void {
    live = true;
    const disconnect = connectKnowledgeGraphEvents({
      onNode: (e) => {
        pendingNodes.push(e);
        scheduleFlush();
      },
      onEdge: (e) => {
        pendingEdges.push(e);
        scheduleFlush();
      },
      onProgress: (e) => {
        progress = e;
      },
      onCompleted: () => {
        progress = null;
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
  //   • node name/aliases + edge rel_type/fact → matched here (client-side)
  //   • chunk TEXT → matched via the backend (KnowledgeGraphPanel fetches point_ids
  //     and pushes them in through setMatchedChunkIds; we map them onto nodes/edges
  //     by chunk_ids, G6). The two match sources union below.
  let searchQuery = $state('');
  // Qdrant point_ids whose chunk text matched the current query (== chunk_ids). Owned
  // here but populated by the panel's debounced backend lookup; cleared when the query
  // clears so a stale chunk match never outlives its text.
  let matchedChunkIds = $state<Set<string>>(new Set());

  function setSearchQuery(q: string): void {
    searchQuery = q;
    if (!q.trim()) matchedChunkIds = new Set(); // clearing the box clears chunk matches too
  }
  function setMatchedChunkIds(ids: string[]): void {
    matchedChunkIds = new Set(ids);
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
    connectEvents,
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
    setSearchQuery,
    setMatchedChunkIds,
    searchActive: () => searchActive,
    matchedNodeIds: () => matchedNodeIds,
    matchedEdgeIds: () => matchedEdgeIds,
    matchCount: () => matchCount
  };
}

export type KnowledgeGraphModel = ReturnType<typeof createKnowledgeGraphModel>;
