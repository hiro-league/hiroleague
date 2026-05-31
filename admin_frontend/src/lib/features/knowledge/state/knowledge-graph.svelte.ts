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

export interface KnowledgeGraphModelDeps {
  setError: (msg: string | null) => void;
}

export type GraphSelection = { kind: 'node'; id: string } | { kind: 'edge'; id: string } | null;

// How long a freshly-created node/edge glows after appearing (ms).
const GLOW_MS = 3000;
// Debounce window for the post-ingest reconciling re-export (ms).
const RECONCILE_DEBOUNCE_MS = 400;

export function createKnowledgeGraphModel(deps: KnowledgeGraphModelDeps) {
  let nodes = $state<GraphNodeDTO[]>([]);
  let links = $state<GraphEdgeDTO[]>([]);
  let loading = $state(false);
  let truncated = $state(false);
  let live = $state(false);
  let progress = $state<GraphIngestProgress | null>(null);
  let selected = $state<GraphSelection>(null);
  // Bumped whenever node/edge membership changes — the panel watches this to
  // push fresh data into the force-graph instance without diffing arrays.
  let dataVersion = $state(0);
  // id (prefixed n:/e:) -> epoch ms of last "is_new" sighting; drives the glow.
  let recent = $state<Record<string, number>>({});

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
    dataVersion += 1;
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

  return {
    nodes: () => nodes,
    links: () => links,
    loading: () => loading,
    truncated: () => truncated,
    live: () => live,
    progress: () => progress,
    dataVersion: () => dataVersion,
    recent: () => recent,
    selected: () => selected,
    selectedNode,
    selectedEdge,
    nodeName,
    selectNode,
    selectEdge,
    clearSelection,
    load,
    connectEvents
  };
}

export type KnowledgeGraphModel = ReturnType<typeof createKnowledgeGraphModel>;
