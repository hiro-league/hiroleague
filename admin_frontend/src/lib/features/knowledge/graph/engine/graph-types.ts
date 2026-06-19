/**
 * Minimal local types for the force-graph canvas engine.
 *
 * force-graph / d3 store live simulation state (x, y, vx, vy, fx, fy, index) directly on
 * the node/link objects we hand them. We keep our own plain (non-reactive) MIRROR objects
 * — see graph-canvas-engine.ts — so positions persist across reactive model rebuilds.
 * These shapes describe those mirror objects (plus the transient fields force-graph adds).
 */

/** A plain mirror node fed to force-graph. Display fields are refreshed from the model;
 *  the simulation fields (x/y/vx/vy/fx/fy/index) are owned by d3 and MUST persist. */
export interface FgNode {
  id: string;
  type: string;
  name: string;
  // d3-force simulation state (assigned by the engine on bind):
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
  index?: number;
  /** Degree-radial target radius (see degreeRadial in graph-forces.ts). */
  __targetR?: number;
  /** Hub-separation support: the node's connection count, stashed by the engine on each
   *  relayout so the charge/collide force accessors can scale by degree without re-deriving it. */
  __degree?: number;
  /** Collision radius (see collideRadius / degreeCollide in graph-forces.ts): the always-on baseline
   *  disc (drawn radius + COLLIDE_PAD) plus any extra hub bubble when "Hub separation" > 0. */
  __collideR?: number;
}

/** A plain mirror link fed to force-graph. `source`/`target` start as node ids and are
 *  rewritten by force-graph into the resolved FgNode objects once the graph is laid out. */
export interface FgLink {
  id: string;
  source: string | FgNode;
  target: string | FgNode;
  rel_type: string;
  /** True when the fact is superseded (invalid_at or expired_at set) — drawn dashed + red. */
  invalid?: boolean;
  /** Per-link curvature for fanned parallel edges (see assignLinkCurvatures). */
  __curvature?: number;
  /** Bezier control points force-graph computes just before the 'after' paint. */
  __controlPoints?: number[] | null;
  /** Set on the synthetic "N other relations" edge that stands in for the parallel edges a pair's
   *  "Visible edges" cap collapsed (see collapseParallelLinks). Drawn solid + a touch thicker. */
  aggregate?: boolean;
  /** Ids of the edges the aggregate represents (length === the "N" shown in its label). */
  collapsedIds?: string[];
  /** True when the aggregate stands in for ALL the pair's relations ("X relations" vs "N other"). */
  whole?: boolean;
}

/** Normalize a link endpoint (id string OR resolved node object) back to its id. */
export const linkEndId = (end: unknown): string =>
  end && typeof end === 'object' ? (end as { id: string }).id : (end as string);
