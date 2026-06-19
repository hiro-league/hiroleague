import type { SearchFocusMode } from '../knowledge-graph-prefs';
import type { FgLink, FgNode } from './graph-types';

/** Reactive node/link shapes handed in from the model (id/type/name + display fields). */
export interface RenderNode {
  id: string;
  type: string;
  name: string;
}

export interface RenderLink {
  id: string;
  source: string | { id: string };
  target: string | { id: string };
  rel_type: string;
  invalid_at?: string | null;
  expired_at?: string | null;
  aggregate?: boolean;
  collapsedIds?: string[];
  whole?: boolean;
}

export interface NeighborFocusState {
  active: boolean;
  mode: 'dim' | 'hide' | 'none';
  selectedId: string;
  nodeIds: Set<string>;
  edgeIds: Set<string>;
}

export interface GraphCanvasCallbacks {
  onNodeClick: (id: string) => void;
  onLinkClick: (id: string) => void;
  onBackgroundClick: () => void;
  onZoomChange?: (k: number) => void;
}

export interface StructuralContext {
  loadVersion: number;
  hiddenNodeIds: Set<string>;
  hiddenEdgeTypes: Set<string>;
  filterToken: string;
}

export interface SearchState {
  searchActive: boolean;
  matchedNodeIds: Set<string>;
  matchedEdgeIds: Set<string>;
  focusNodeIds: Set<string> | null;
  searchFocusMode: SearchFocusMode;
}

export type GraphSelection = { kind: 'node' | 'edge'; id: string } | null;

/** Aggregate-edge label: "X relations" when whole, else "N other relations". */
export function aggregateLabel(l: FgLink): string {
  const n = l.collapsedIds?.length ?? 0;
  return l.whole ? `${n} relations` : `${n} other relations`;
}

/** Below this "Node fade" opacity a node is treated as gone. */
export const FADE_CULL_EPSILON = 0.012;

/** Multiply the alpha channel of an rgba/rgb colour by factor (clamped 0..1). */
export function scaleColorAlpha(color: string, factor: number): string {
  if (factor >= 1) return color;
  const m = color.match(/^rgba?\(([^)]+)\)$/i);
  if (!m) return color;
  const p = m[1].split(',').map((s) => s.trim());
  if (p.length < 3) return color;
  const a = p.length >= 4 ? parseFloat(p[3]) : 1;
  return `rgba(${p[0]},${p[1]},${p[2]},${Math.max(0, Math.min(1, a * factor))})`;
}
