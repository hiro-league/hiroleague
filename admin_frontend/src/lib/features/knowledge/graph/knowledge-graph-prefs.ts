/**
 * Persistence for the Knowledge Graph view's layout controls.
 *
 * The four "Graph options" sliders are local view preferences, so they live in
 * localStorage (durable across reloads and fresh navigation) rather than the URL.
 * Filters keep their own URL+localStorage handling in knowledge-graph.svelte.ts
 * (URL stays shareable); these helpers cover only the options sliders.
 */
import { PREF_KEYS, type GraphPanelSidePreference } from '$lib/preferences/keys';
import {
  readLocalString,
  readSessionString,
  writeLocalString,
  writeSessionString
} from '$lib/preferences/storage';
import {
  CENTER_STRENGTH,
  CHARGE_STRENGTH,
  COLLIDE_SCALE_DEFAULT,
  NODE_FADE_FULL_DEFAULT,
  NODE_FADE_START_DEFAULT,
  NODE_REVEAL_LO_DEFAULT,
  NODE_REVEAL_HI_DEFAULT,
  RADIAL_RING
} from './engine/graph-forces';
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

/** Node-node repulsion ("charge") slider bounds. d3 charge is NEGATIVE (repulsion); more
 *  negative = nodes push apart harder (airier). 0 = no repulsion. Left = spread, right = clump. */
export const CHARGE_STRENGTH_MIN = -600;
export const CHARGE_STRENGTH_MAX = 0;

/** "Hub separation" slider bounds. 0 = off (layout identical to before the feature); higher
 *  pushes high-degree hubs apart from each other (charge/collide scaled by √degree). */
export const HUB_SEPARATION_MIN = 0;
export const HUB_SEPARATION_MAX = 1;

/** "Hub spacing" slider bounds — the multiplier for HOW FAR hubs settle apart (collide bubble +
 *  charge reach + inner band). 1 = the baseline spread; higher pushes hubs much further out. Only
 *  has an effect while Hub separation > 0. */
export const HUB_SPACING_MIN = 0.5;
export const HUB_SPACING_MAX = 6;

/** "Collision spacing" slider bounds — a multiplier on every node's collide radius. 1 = normal
 *  spacing; higher opens extra room so node labels are less likely to cover neighbours. */
export const COLLIDE_SCALE_MIN = 1;
export const COLLIDE_SCALE_MAX = 3;

/** "Node fade" range bounds — the prominence (normalizedDegree × zoom) thresholds at which a node is
 *  fully transparent (start) → fully solid (full). 0..0 disables it. Bound generously since zoom can
 *  push prominence past 1 for hubs when zoomed in. */
export const NODE_FADE_MIN = 0;
export const NODE_FADE_MAX = 1; // thresholds are in importance units (0..1 log-degree)

/** "Zoom reveal" range bounds, in ZOOM units (match the on-canvas zoom readout). Hazy below the low
 *  thumb → clear above the high thumb. Generous span so any fit/overview zoom sits inside it. */
export const NODE_REVEAL_ZOOM_MIN = 0.1;
export const NODE_REVEAL_ZOOM_MAX = 6;

/** "Node size" 2-knob range bounds (drawn disc radius in graph units). The min/max knobs map the
 *  least- and most-connected nodes; equal min/max = flat (every node the same). Default 8–22. */
export const NODE_SIZE_BOUND_MIN = 4;
export const NODE_SIZE_BOUND_MAX = 100;

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
  /** d3 charge (node-node repulsion); negative = repulsion. Live "Node repulsion" slider. */
  chargeStrength: number;
  /** "Hub separation": 0 off … 1 max. Scales the per-node charge/collide forces by √degree so
   *  high-degree hubs settle farther apart from one another (dense graphs read less clumped). */
  hubSeparation: number;
  /** "Hub spacing": multiplier for HOW FAR hubs spread (collide bubble + charge reach + band).
   *  1 = baseline; higher pushes hubs much further. Inert while hubSeparation = 0. */
  hubSpacing: number;
  /** "Collision spacing": multiplier on every node's collide radius (1 = normal). Higher opens room
   *  so node labels are less likely to cover neighbours. */
  collideScale: number;
  /** "Node fade" range: prominence (normalizedDegree × zoom) at which a node is fully transparent
   *  (start) and fully solid (full). full ≤ start disables it (every node solid). Declutters by
   *  fading small/far nodes; independent of the node-size/font sliders. */
  nodeFadeStart: number;
  nodeFadeFull: number;
  /** "Zoom reveal" range (ZOOM units): hazy below `nodeRevealLo×` → clear above `nodeRevealHi×`.
   *  Lifts node clarity as you zoom in. hi ≤ lo → static (no zoom motion). */
  nodeRevealLo: number;
  nodeRevealHi: number;
  /** "Node size" range: drawn radius for the least-connected (min) → most-connected (max) node,
   *  scaled by √degree. Equal min/max = flat (uniform size). Font scales with size too. */
  nodeSizeMin: number;
  nodeSizeMax: number;
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
  chargeStrength: CHARGE_STRENGTH,
  hubSeparation: 0, // off by default → identical to the pre-feature layout
  hubSpacing: 1, // baseline spread when hub separation is enabled
  collideScale: COLLIDE_SCALE_DEFAULT, // 1 = normal collide radius (no extra label spacing)
  nodeFadeStart: NODE_FADE_START_DEFAULT, // 0/0 = node fade OFF (every node fully solid)
  nodeFadeFull: NODE_FADE_FULL_DEFAULT,
  nodeRevealLo: NODE_REVEAL_LO_DEFAULT, // zoom-reveal: hazy below this zoom…
  nodeRevealHi: NODE_REVEAL_HI_DEFAULT, // …clear above this zoom (only active once Node fade is on)
  nodeSizeMin: 8, // degree-based sizing ON by default (least-connected radius)
  nodeSizeMax: 22, // most-connected radius
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
      chargeStrength: clamp(
        num(p.chargeStrength, GRAPH_OPTION_DEFAULTS.chargeStrength),
        CHARGE_STRENGTH_MIN,
        CHARGE_STRENGTH_MAX
      ),
      hubSeparation: clamp(
        num(p.hubSeparation, GRAPH_OPTION_DEFAULTS.hubSeparation),
        HUB_SEPARATION_MIN,
        HUB_SEPARATION_MAX
      ),
      hubSpacing: clamp(
        num(p.hubSpacing, GRAPH_OPTION_DEFAULTS.hubSpacing),
        HUB_SPACING_MIN,
        HUB_SPACING_MAX
      ),
      collideScale: clamp(
        num(p.collideScale, GRAPH_OPTION_DEFAULTS.collideScale),
        COLLIDE_SCALE_MIN,
        COLLIDE_SCALE_MAX
      ),
      nodeFadeStart: clamp(
        num(p.nodeFadeStart, GRAPH_OPTION_DEFAULTS.nodeFadeStart),
        NODE_FADE_MIN,
        NODE_FADE_MAX
      ),
      nodeFadeFull: clamp(
        num(p.nodeFadeFull, GRAPH_OPTION_DEFAULTS.nodeFadeFull),
        NODE_FADE_MIN,
        NODE_FADE_MAX
      ),
      nodeRevealLo: clamp(
        num(p.nodeRevealLo, GRAPH_OPTION_DEFAULTS.nodeRevealLo),
        NODE_REVEAL_ZOOM_MIN,
        NODE_REVEAL_ZOOM_MAX
      ),
      nodeRevealHi: clamp(
        num(p.nodeRevealHi, GRAPH_OPTION_DEFAULTS.nodeRevealHi),
        NODE_REVEAL_ZOOM_MIN,
        NODE_REVEAL_ZOOM_MAX
      ),
      nodeSizeMin: clamp(
        num(p.nodeSizeMin, GRAPH_OPTION_DEFAULTS.nodeSizeMin),
        NODE_SIZE_BOUND_MIN,
        NODE_SIZE_BOUND_MAX
      ),
      nodeSizeMax: clamp(
        num(p.nodeSizeMax, GRAPH_OPTION_DEFAULTS.nodeSizeMax),
        NODE_SIZE_BOUND_MIN,
        NODE_SIZE_BOUND_MAX
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

// ── Graph-options section collapse state ───────────────────────────────────
// Whether each Graph-options accordion section is expanded. Persisted so the panel reopens with
// the same sections folded (the panel unmounts when closed, so without this it reset every open).
export type GraphOptionSections = { filters: boolean; view: boolean; physics: boolean };
const GRAPH_OPTION_SECTIONS_DEFAULT: GraphOptionSections = { filters: true, view: true, physics: true };

export function readGraphOptionSections(): GraphOptionSections {
  const raw = readLocalString(PREF_KEYS.knowledgeGraphOptionSections);
  if (!raw) return { ...GRAPH_OPTION_SECTIONS_DEFAULT };
  try {
    const p = JSON.parse(raw) as Partial<GraphOptionSections>;
    return {
      filters: typeof p.filters === 'boolean' ? p.filters : true,
      view: typeof p.view === 'boolean' ? p.view : true,
      physics: typeof p.physics === 'boolean' ? p.physics : true
    };
  } catch {
    return { ...GRAPH_OPTION_SECTIONS_DEFAULT };
  }
}

export function writeGraphOptionSections(s: GraphOptionSections): void {
  writeLocalString(PREF_KEYS.knowledgeGraphOptionSections, JSON.stringify(s));
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

// ── Deep-link focus seeding ────────────────────────────────────────────────
/**
 * Seed sessionStorage so the Knowledge Graph view opens focused on ONE episode of ONE partition:
 * sets the active group and that group's episode-filter selection to `[episodeId]` (merged into any
 * existing per-group selections). The graph model restores both on mount (`loadGroups` →
 * `activeGroupId`, `loadEpisodes` → `episodeChunkIds`), so a deep-link such as the eval Corpus tab's
 * "graph" button (→ `/memories?tab=graph`) lands pre-filtered with NO graph-page change. Uses the
 * SAME session keys + JSON-map format the graph model reads (`{ group_id: chunk_id[] }`).
 */
export function seedGraphEpisodeFocus(groupId: string, episodeId: string): void {
  if (!groupId || !episodeId) return;
  writeSessionString(PREF_KEYS.knowledgeGraphActiveGroup, groupId);
  let map: Record<string, string[]> = {};
  const raw = readSessionString(PREF_KEYS.knowledgeGraphEpisodeSel);
  if (raw) {
    try {
      map = JSON.parse(raw) as Record<string, string[]>;
    } catch {
      map = {}; // corrupt blob → start fresh
    }
  }
  map[groupId] = [episodeId];
  writeSessionString(PREF_KEYS.knowledgeGraphEpisodeSel, JSON.stringify(map));
}
