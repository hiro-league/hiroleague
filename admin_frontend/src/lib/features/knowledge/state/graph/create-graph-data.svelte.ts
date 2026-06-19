import {
  exportKnowledgeGraph,
  type GraphEdgeDTO,
  type GraphEdgeEvent,
  type GraphIngestProgress,
  type GraphNodeDTO,
  type GraphNodeEvent
} from '$lib/api/knowledge';
import { getPreferences } from '$lib/api/preferences';
import { connectKnowledgeGraphEvents } from '../../shared/knowledge-events';
import { GLOW_MS } from '../../graph/engine/graph-config';
import { linkEndId } from '../../graph/engine/graph-types';
import { DEFAULT_LARGE_TYPE_THRESHOLD, RECONCILE_DEBOUNCE_MS } from './graph-types';
import type { GraphSelection } from './graph-types';

export interface GraphDataStoreDeps {
  setError: (msg: string | null) => void;
  getActiveGroupId: () => string | null;
  eventMatchesActiveGroup: (gid: string | null | undefined) => boolean;
  onLoadComplete: () => void;
  onTeardownSearch: () => void;
  refreshGroups: () => Promise<void>;
}

export function createGraphDataStore(deps: GraphDataStoreDeps) {
  let nodes = $state<GraphNodeDTO[]>([]);
  let links = $state<GraphEdgeDTO[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);
  let truncated = $state(false);
  let loadVersion = $state(0);
  let live = $state(false);
  let progress = $state<GraphIngestProgress | null>(null);
  let selected = $state<GraphSelection>(null);
  let recent = $state<Record<string, number>>({});
  let largeTypeThreshold = $state(DEFAULT_LARGE_TYPE_THRESHOLD);

  const nodeById = new Map<string, GraphNodeDTO>();
  const edgeById = new Map<string, GraphEdgeDTO>();

  let pendingNodes: GraphNodeEvent[] = [];
  let pendingEdges: GraphEdgeEvent[] = [];
  let flushScheduled = false;
  let reconcileTimer: ReturnType<typeof setTimeout> | null = null;

  function rebuildArrays(): void {
    nodes = [...nodeById.values()];
    links = [...edgeById.values()].filter(
      (e) => nodeById.has(linkEndId(e.source)) && nodeById.has(linkEndId(e.target))
    );
  }

  function upsertNode(dto: GraphNodeDTO): void {
    const existing = nodeById.get(dto.id);
    if (existing) {
      Object.assign(existing, dto);
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
      const activeGroupId = deps.getActiveGroupId();
      const res = await exportKnowledgeGraph(activeGroupId ? { groupIds: [activeGroupId] } : {});
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
      loadVersion += 1;
      deps.onLoadComplete();
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
      deps.setError(loadError);
    } finally {
      loading = false;
    }
  }

  async function loadPreferences(): Promise<void> {
    try {
      const res = await getPreferences();
      const t = res.data?.preferences?.graph?.view?.large_type_threshold;
      if (typeof t === 'number' && t > 0) largeTypeThreshold = t;
    } catch (err) {
      console.error('graph: failed to load view preferences', err);
    }
  }

  function connectEvents(): () => void {
    live = true;
    const disconnect = connectKnowledgeGraphEvents({
      onNode: (e) => {
        if (!deps.eventMatchesActiveGroup(e.group_id)) return;
        pendingNodes.push(e);
        scheduleFlush();
      },
      onEdge: (e) => {
        if (!deps.eventMatchesActiveGroup(e.group_id)) return;
        pendingEdges.push(e);
        scheduleFlush();
      },
      onProgress: (e) => {
        if (!deps.eventMatchesActiveGroup(e.group_id)) return;
        progress = e;
      },
      onCompleted: (gid) => {
        void deps.refreshGroups();
        if (gid != null && !deps.eventMatchesActiveGroup(gid)) return;
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
      deps.onTeardownSearch();
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
    get nodes() {
      return nodes;
    },
    get links() {
      return links;
    },
    get loading() {
      return loading;
    },
    get loadError() {
      return loadError;
    },
    get loadVersion() {
      return loadVersion;
    },
    get truncated() {
      return truncated;
    },
    get live() {
      return live;
    },
    get progress() {
      return progress;
    },
    get recent() {
      return recent;
    },
    get selected() {
      return selected;
    },
    get largeTypeThreshold() {
      return largeTypeThreshold;
    },
    load,
    loadPreferences,
    connectEvents,
    selectNode,
    selectEdge,
    clearSelection,
    selectedNode,
    selectedEdge,
    nodeName
  };
}

export type GraphDataStore = ReturnType<typeof createGraphDataStore>;
