import type { GraphEdgeDTO, GraphNodeDTO } from '$lib/api/knowledge';
import { linkEndId } from '../../graph/engine/graph-types';
import {
  readHidden,
  SESSION_HIDE_EDGES,
  SESSION_HIDE_NODES,
  writeHidden
} from './graph-persistence';

export function createGraphViewFilters() {
  let hiddenNodeIds = $state<Set<string>>(readHidden(SESSION_HIDE_NODES));
  let hiddenEdgeTypes = $state<Set<string>>(readHidden(SESSION_HIDE_EDGES));

  function setVisibleNodeIds(type: string, visible: string[], nodes: GraphNodeDTO[]): void {
    const shown = new Set(visible);
    const next = new Set(hiddenNodeIds);
    for (const n of nodes) {
      if (n.type !== type) continue;
      if (shown.has(n.id)) next.delete(n.id);
      else next.add(n.id);
    }
    hiddenNodeIds = next;
    writeHidden(SESSION_HIDE_NODES, next);
  }

  function setVisibleEdgeTypes(visible: string[], links: GraphEdgeDTO[]): void {
    const shown = new Set(visible);
    const next = new Set<string>();
    for (const e of links) {
      if (!shown.has(e.rel_type)) next.add(e.rel_type);
    }
    hiddenEdgeTypes = next;
    writeHidden(SESSION_HIDE_EDGES, next);
  }

  function clearViewFilters(): void {
    hiddenNodeIds = new Set();
    hiddenEdgeTypes = new Set();
    writeHidden(SESSION_HIDE_NODES, hiddenNodeIds);
    writeHidden(SESSION_HIDE_EDGES, hiddenEdgeTypes);
  }

  return {
    get hiddenNodeIds() {
      return hiddenNodeIds;
    },
    get hiddenEdgeTypes() {
      return hiddenEdgeTypes;
    },
    setVisibleNodeIds,
    setVisibleEdgeTypes,
    clearViewFilters
  };
}

export type GraphViewFilters = ReturnType<typeof createGraphViewFilters>;
