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
import { CENTER_STRENGTH, RADIAL_RING } from './engine/graph-forces';

/** Cap on parallel edges per node pair that means "show all" — also the slider max. */
export const MAX_LINKS_CAP = 10;

/** How the search highlight treats NON-matching nodes/edges:
 *  'highlight' = ring matches only, leave others as-is · 'dim' = fade others ·
 *  'hide' = render others invisible (layout unchanged, so clearing restores instantly). */
export type SearchFocusMode = 'highlight' | 'dim' | 'hide';
const SEARCH_FOCUS_MODES: readonly SearchFocusMode[] = ['highlight', 'dim', 'hide'];

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
  /** What a search does to non-matching nodes/edges (see SearchFocusMode). */
  searchFocusMode: SearchFocusMode;
};

// Center/spread defaults come from the force constants so there's a single source of truth.
export const CENTER_STRENGTH_MIN = 0;
export const CENTER_STRENGTH_MAX = 0.5;
export const RADIAL_RING_MIN = 20;
export const RADIAL_RING_MAX = 200;

export const GRAPH_OPTION_DEFAULTS: GraphOptions = {
  linkStrength: 0.5,
  linkDistance: 80,
  centerStrength: CENTER_STRENGTH,
  radialRing: RADIAL_RING,
  curveAmount: 0.45,
  maxLinksPerPair: MAX_LINKS_CAP,
  searchFocusMode: 'highlight'
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
      searchFocusMode: SEARCH_FOCUS_MODES.includes(p.searchFocusMode as SearchFocusMode)
        ? (p.searchFocusMode as SearchFocusMode)
        : GRAPH_OPTION_DEFAULTS.searchFocusMode
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
