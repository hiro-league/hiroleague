/**
 * Persistence for the Knowledge Graph view's layout controls.
 *
 * The four "Graph options" sliders are local view preferences, so they live in
 * localStorage (durable across reloads and fresh navigation) rather than the URL.
 * Filters keep their own URL+localStorage handling in knowledge-graph.svelte.ts
 * (URL stays shareable); these helpers cover only the options sliders.
 */
import { PREF_KEYS, type GraphPanelSidePreference } from '$lib/preferences/keys';
import { readLocalString, writeLocalString } from '$lib/preferences/storage';
import { CENTER_STRENGTH, CHARGE_STRENGTH, RADIAL_RING } from './engine/graph-forces';
import {
  EDGE_FONT_MAX,
  EDGE_FONT_MIN,
  EDGE_ZOOM_MAX,
  EDGE_ZOOM_MIN,
  NODE_FONT_MAX,
  NODE_FONT_MIN,
  NODE_ZOOM_MAX,
  NODE_ZOOM_MIN
} from './engine/graph-config';

/** Cap on parallel edges per node pair that means "show all" — also the slider max. */
export const MAX_LINKS_CAP = 10;

/** Node-node repulsion ("charge") slider bounds. d3 charge is NEGATIVE (repulsion); more
 *  negative = nodes push apart harder (airier). 0 = no repulsion. Left = spread, right = clump. */
export const CHARGE_STRENGTH_MIN = -600;
export const CHARGE_STRENGTH_MAX = 0;

/** Bounds for the label-sizing range sliders (View → font controls). */
export const LABEL_ZOOM_BOUND_MIN = 0.2; // zoom level at which a label first appears / clamps
export const LABEL_ZOOM_BOUND_MAX = 6;
export const LABEL_FONT_BOUND_MIN = 4; // on-screen px
export const LABEL_FONT_BOUND_MAX = 40;
/** Edge-label truncation (X letters) slider bounds. */
export const EDGE_LABEL_MAX_MIN = 6;
export const EDGE_LABEL_MAX_MAX = 48;

/** How the search highlight treats NON-matching nodes/edges:
 *  'highlight' = ring matches only, leave others as-is · 'dim' = fade others ·
 *  'hide' = render others invisible (layout unchanged, so clearing restores instantly). */
export type SearchFocusMode = 'highlight' | 'dim' | 'hide';
const SEARCH_FOCUS_MODES: readonly SearchFocusMode[] = ['highlight', 'dim', 'hide'];

/** How a SELECTED node focuses its neighborhood (node + directly-connected nodes/edges):
 *  'all' = no focus · 'dim' = fade everything else · 'hide' = render everything else invisible.
 *  Renderer-only (no relayout) so clicking around stays snappy. */
export type SelectionFocusMode = 'all' | 'dim' | 'hide';
const SELECTION_FOCUS_MODES: readonly SelectionFocusMode[] = ['all', 'dim', 'hide'];

export type GraphOptions = {
  /** d3 link-force strength: 0 loose … 1 rigid. */
  linkStrength: number;
  /** d3 link-force resting length, in px. */
  linkDistance: number;
  /** d3 center-force strength: pulls ALL nodes (incl. disconnected ones) toward the middle.
   *  0 = no pull (clusters drift far) … higher = tighter overall graph. */
  centerStrength: number;
  /** Outer-ring radius for the degree-radial force, in px (scaled by √node-count by the
   *  engine). Lower pulls least-connected / disconnected strays inward; higher pushes out. */
  radialRing: number;
  /** Max bow for fanned parallel edges: 0 straight … 1 very curved. */
  curveAmount: number;
  /** Max parallel edges drawn per node pair; MAX_LINKS_CAP = show all. */
  maxLinksPerPair: number;
  /** d3 charge (node-node repulsion); negative = repulsion. Live "Node repulsion" slider. */
  chargeStrength: number;
  /** What a search does to non-matching nodes/edges (see SearchFocusMode). */
  searchFocusMode: SearchFocusMode;
  /** What a SELECTED node does to the rest of the graph (see SelectionFocusMode). */
  selectionFocusMode: SelectionFocusMode;
  // ── Label sizing (live; replaces the former hardcoded graph-config constants) ──
  /** Edge label: zoom at which it appears (min) → clamps to full size (max). */
  edgeZoomMin: number;
  edgeZoomMax: number;
  /** Edge label: on-screen px at min-zoom → max-zoom. */
  edgeFontMin: number;
  edgeFontMax: number;
  /** Node label zoom + font, same meaning as the edge pair. */
  nodeZoomMin: number;
  nodeZoomMax: number;
  nodeFontMin: number;
  nodeFontMax: number;
  /** Trim edge labels longer than this many characters (with an ellipsis). */
  edgeLabelMax: number;
};

// Center/spread defaults come from the force constants so there's a single source of truth.
export const CENTER_STRENGTH_MIN = 0;
export const CENTER_STRENGTH_MAX = 0.5;
export const RADIAL_RING_MIN = 0;
export const RADIAL_RING_MAX = 200;

export const GRAPH_OPTION_DEFAULTS: GraphOptions = {
  linkStrength: 0.5,
  linkDistance: 80,
  centerStrength: CENTER_STRENGTH,
  radialRing: RADIAL_RING,
  curveAmount: 0.15,
  maxLinksPerPair: MAX_LINKS_CAP,
  chargeStrength: CHARGE_STRENGTH,
  searchFocusMode: 'highlight',
  selectionFocusMode: 'all',
  edgeZoomMin: EDGE_ZOOM_MIN,
  edgeZoomMax: EDGE_ZOOM_MAX,
  edgeFontMin: EDGE_FONT_MIN,
  edgeFontMax: EDGE_FONT_MAX,
  nodeZoomMin: NODE_ZOOM_MIN,
  nodeZoomMax: NODE_ZOOM_MAX,
  nodeFontMin: NODE_FONT_MIN,
  nodeFontMax: NODE_FONT_MAX,
  edgeLabelMax: 22
};

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
// Coerce + guard against NaN/garbage in stored JSON (?? only catches null/undefined).
const num = (v: unknown, def: number): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
};

/** Read persisted options, clamped to valid ranges; defaults when absent/corrupt. */
export function readGraphOptions(): GraphOptions {
  const raw = readLocalString(PREF_KEYS.knowledgeGraphOptions);
  if (!raw) return { ...GRAPH_OPTION_DEFAULTS };
  try {
    const p = JSON.parse(raw) as Partial<GraphOptions>;
    return {
      linkStrength: clamp(num(p.linkStrength, GRAPH_OPTION_DEFAULTS.linkStrength), 0, 1),
      linkDistance: clamp(num(p.linkDistance, GRAPH_OPTION_DEFAULTS.linkDistance), 20, 300),
      centerStrength: clamp(
        num(p.centerStrength, GRAPH_OPTION_DEFAULTS.centerStrength),
        CENTER_STRENGTH_MIN,
        CENTER_STRENGTH_MAX
      ),
      radialRing: clamp(
        num(p.radialRing, GRAPH_OPTION_DEFAULTS.radialRing),
        RADIAL_RING_MIN,
        RADIAL_RING_MAX
      ),
      curveAmount: clamp(num(p.curveAmount, GRAPH_OPTION_DEFAULTS.curveAmount), 0, 1),
      maxLinksPerPair: clamp(
        Math.round(num(p.maxLinksPerPair, GRAPH_OPTION_DEFAULTS.maxLinksPerPair)),
        1,
        MAX_LINKS_CAP
      ),
      chargeStrength: clamp(
        num(p.chargeStrength, GRAPH_OPTION_DEFAULTS.chargeStrength),
        CHARGE_STRENGTH_MIN,
        CHARGE_STRENGTH_MAX
      ),
      searchFocusMode: SEARCH_FOCUS_MODES.includes(p.searchFocusMode as SearchFocusMode)
        ? (p.searchFocusMode as SearchFocusMode)
        : GRAPH_OPTION_DEFAULTS.searchFocusMode,
      selectionFocusMode: SELECTION_FOCUS_MODES.includes(p.selectionFocusMode as SelectionFocusMode)
        ? (p.selectionFocusMode as SelectionFocusMode)
        : GRAPH_OPTION_DEFAULTS.selectionFocusMode,
      edgeZoomMin: clamp(num(p.edgeZoomMin, GRAPH_OPTION_DEFAULTS.edgeZoomMin), LABEL_ZOOM_BOUND_MIN, LABEL_ZOOM_BOUND_MAX),
      edgeZoomMax: clamp(num(p.edgeZoomMax, GRAPH_OPTION_DEFAULTS.edgeZoomMax), LABEL_ZOOM_BOUND_MIN, LABEL_ZOOM_BOUND_MAX),
      edgeFontMin: clamp(num(p.edgeFontMin, GRAPH_OPTION_DEFAULTS.edgeFontMin), LABEL_FONT_BOUND_MIN, LABEL_FONT_BOUND_MAX),
      edgeFontMax: clamp(num(p.edgeFontMax, GRAPH_OPTION_DEFAULTS.edgeFontMax), LABEL_FONT_BOUND_MIN, LABEL_FONT_BOUND_MAX),
      nodeZoomMin: clamp(num(p.nodeZoomMin, GRAPH_OPTION_DEFAULTS.nodeZoomMin), LABEL_ZOOM_BOUND_MIN, LABEL_ZOOM_BOUND_MAX),
      nodeZoomMax: clamp(num(p.nodeZoomMax, GRAPH_OPTION_DEFAULTS.nodeZoomMax), LABEL_ZOOM_BOUND_MIN, LABEL_ZOOM_BOUND_MAX),
      nodeFontMin: clamp(num(p.nodeFontMin, GRAPH_OPTION_DEFAULTS.nodeFontMin), LABEL_FONT_BOUND_MIN, LABEL_FONT_BOUND_MAX),
      nodeFontMax: clamp(num(p.nodeFontMax, GRAPH_OPTION_DEFAULTS.nodeFontMax), LABEL_FONT_BOUND_MIN, LABEL_FONT_BOUND_MAX),
      edgeLabelMax: clamp(
        Math.round(num(p.edgeLabelMax, GRAPH_OPTION_DEFAULTS.edgeLabelMax)),
        EDGE_LABEL_MAX_MIN,
        EDGE_LABEL_MAX_MAX
      )
    };
  } catch {
    return { ...GRAPH_OPTION_DEFAULTS };
  }
}

export function writeGraphOptions(opts: GraphOptions): void {
  writeLocalString(PREF_KEYS.knowledgeGraphOptions, JSON.stringify(opts));
}

// ── Detail-panel dock side ─────────────────────────────────────────────────
// Which side the selection/detail aside docks on. 'auto' follows the chat overlay
// (left while chat is open so the panel isn't covered, right otherwise); 'left'/'right'
// pin it. Default 'auto'.
const PANEL_SIDES: readonly GraphPanelSidePreference[] = ['auto', 'left', 'right'];

export function readGraphPanelSide(): GraphPanelSidePreference {
  const raw = readLocalString(PREF_KEYS.knowledgeGraphPanelSide);
  return PANEL_SIDES.includes(raw as GraphPanelSidePreference)
    ? (raw as GraphPanelSidePreference)
    : 'auto';
}

export function writeGraphPanelSide(side: GraphPanelSidePreference): void {
  writeLocalString(PREF_KEYS.knowledgeGraphPanelSide, side);
}
