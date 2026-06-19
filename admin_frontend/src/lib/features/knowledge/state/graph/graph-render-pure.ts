import type { GraphEdgeDTO, GraphNodeDTO } from '$lib/api/knowledge';
import type { SearchFocusMode, SelectionFocusMode } from '../../graph/knowledge-graph-prefs';
import { linkEndId } from '../../graph/engine/graph-types';
import type { NeighborFocusState } from '../../graph/engine/graph-engine-types';

export type DisplayLink = {
  id: string;
  source: string | { id: string };
  target: string | { id: string };
  rel_type: string;
  invalid_at?: string | null;
  expired_at?: string | null;
  aggregate?: boolean;
  collapsedIds?: string[];
  whole?: boolean;
};

export function computeFocusNodeIds(
  searchActive: boolean,
  matchedNodeIds: Set<string>,
  matchedEdgeIds: Set<string>,
  displayLinks: DisplayLink[]
): Set<string> | null {
  if (!searchActive) return null;
  const ids = new Set<string>(matchedNodeIds);
  if (matchedEdgeIds.size > 0) {
    for (const l of displayLinks) {
      if (matchedEdgeIds.has(l.id)) {
        ids.add(String(linkEndId(l.source)));
        ids.add(String(linkEndId(l.target)));
      }
    }
  }
  return ids;
}

export function computeRenderSubset(input: {
  visibleNodes: GraphNodeDTO[];
  displayLinks: DisplayLink[];
  hideMode: boolean;
  focusNodeIds: Set<string> | null;
  matchedEdgeIds: Set<string>;
}): { renderNodes: GraphNodeDTO[]; renderLinks: DisplayLink[] } {
  const renderNodes =
    input.hideMode && input.focusNodeIds
      ? input.visibleNodes.filter((n) => input.focusNodeIds!.has(n.id))
      : input.visibleNodes;
  const renderLinks = input.hideMode
    ? input.displayLinks.filter((l) => input.matchedEdgeIds.has(l.id))
    : input.displayLinks;
  return { renderNodes, renderLinks };
}

export function computeNeighborFocus(input: {
  searchActive: boolean;
  selectionFocusMode: SelectionFocusMode;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  displayLinks: DisplayLink[];
}): NeighborFocusState {
  const inactive: NeighborFocusState = {
    active: false,
    mode: 'dim',
    selectedId: '',
    nodeIds: new Set(),
    edgeIds: new Set()
  };
  if (input.searchActive) return inactive;
  const mode =
    input.selectionFocusMode === 'hide'
      ? ('hide' as const)
      : input.selectionFocusMode === 'dim'
        ? ('dim' as const)
        : ('none' as const);

  if (input.selectedNodeId) {
    const nodeIds = new Set<string>([input.selectedNodeId]);
    const edgeIds = new Set<string>();
    for (const l of input.displayLinks) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      if (a === input.selectedNodeId || b === input.selectedNodeId) {
        edgeIds.add(l.id);
        nodeIds.add(a);
        nodeIds.add(b);
      }
    }
    return { active: true, mode, selectedId: input.selectedNodeId, nodeIds, edgeIds };
  }

  if (input.selectedEdgeId) {
    const l = input.displayLinks.find((x) => x.id === input.selectedEdgeId);
    if (!l) return inactive;
    const a = String(linkEndId(l.source));
    const b = String(linkEndId(l.target));
    return {
      active: true,
      mode,
      selectedId: input.selectedEdgeId,
      nodeIds: new Set([a, b]),
      edgeIds: new Set([input.selectedEdgeId])
    };
  }

  return inactive;
}

export type SearchFocusInput = {
  searchActive: boolean;
  searchFocusMode: SearchFocusMode;
};

export function isSearchHideMode(input: SearchFocusInput): boolean {
  return input.searchActive && input.searchFocusMode === 'hide';
}
