/**
 * d3-force tuning constants + the custom degree-radial centrality force for the knowledge
 * graph layout. These override force-graph's d3-force defaults to give the small
 * personal-KG corpus a less-clumped layout.
 *
 * Rough scaling guide for THIS corpus shape (~50 nodes):
 *   tighter cluster:  LINK_DISTANCE 40,  CHARGE_STRENGTH -80,   CENTER 0.2
 *   balanced (now):   LINK_DISTANCE 80,  CHARGE_STRENGTH -240,  CENTER 0.05
 *   airy / spread:    LINK_DISTANCE 140, CHARGE_STRENGTH -500,  CENTER 0.03
 *   wide overview:    LINK_DISTANCE 200, CHARGE_STRENGTH -800,  CENTER 0.02
 * Negative CHARGE_STRENGTH = repulsion; less negative (or positive) = attract.
 * CENTER_STRENGTH < 1 loosens the pull-to-(0,0) so clusters can drift apart.
 * LINK_DISTANCE/strength are the live "Link distance"/"Link strength" sliders.
 */
import type { FgNode } from './graph-types';

export const CHARGE_STRENGTH = -240;
// DEFAULT for the live "Center pull" slider (knowledge-graph-prefs.centerStrength). The d3
// center force is connectivity-blind, so it's the one knob that reels disconnected nodes /
// detached components back toward the middle. Higher = tighter overall graph.
export const CENTER_STRENGTH = 0.05;
// Keeping orphaned / weakly-connected nodes from flying off:
//  - GRAVITY pulls every node gently toward the origin. Links + charge dominate locally,
//    so connected clusters keep their shape; the weak pull only matters for strays.
//  - CHARGE_DISTANCE_MAX caps how far node-node repulsion reaches, so a lone node isn't
//    shoved across the canvas by the whole cluster's cumulative charge.
export const GRAVITY_STRENGTH = 0.03;
export const CHARGE_DISTANCE_MAX = 320;
// Degree-based "centrality" layout: pull strength toward the per-node target ring, and
// how far the outermost (least-connected) ring sits.
export const RADIAL_STRENGTH = 0.08;

// ── Hub separation (the "Hub separation" slider, 0 = off) ─────────────────────────────────
// Goal: pull high-degree hubs apart from EACH OTHER so a dense graph doesn't read as one
// clump. Three coupled effects, ALL scaled by `hubSep` so hubSep=0 reproduces today's layout
// exactly (multiplier 1 / radius 0 / band 0):
//   1. charge ∝ √degree   — hubs repel everything (incl. other hubs) harder           (long range)
//   2. collide ∝ √degree  — each hub gets a personal-space bubble it can't be overlapped (short range)
//   3. inner band         — hubs aim at a small ring instead of radius 0, so degreeRadial stops
//                           reeling every hub into the exact same centre point.
// `hubSeparation` (0..1) = how aggressively hubs repel (charge intensity + engages collide/band).
// `hubSpacing` (multiplier, ≥0) = HOW FAR hubs settle apart: scales the collide bubble, the
// distanceMax reach, and the inner band so the user can push hubs out well past the old ceiling.
// We scale by `hubFactor` = max(0, √degree − 1), NOT raw √degree, so LEAF nodes (degree 1 → 0)
// keep their normal physics and only genuine hubs grow a bubble / extra charge — otherwise a big
// spacing would inflate the whole graph instead of separating hubs specifically.
export const HUB_CHARGE_GAIN = 0.6; // charge multiplier per unit hubFactor at hubSep=1
export const HUB_CHARGE_MULT_MAX = 8; // clamp the charge multiplier so a mega-hub can't explode
export const HUB_COLLIDE_GAIN = 14; // extra collide radius (px) per unit hubFactor at hubSep=1, spacing=1
export const HUB_DISTANCE_GAIN = 1; // distanceMax growth per unit (hubSep·spacing) so the push has reach
export const HUB_BAND_FRACTION = 0.25; // inner-ring radius at hubSep=1, spacing=1, as a fraction of outerRing
export const HUB_BAND_FRACTION_MAX = 0.85; // cap the band so hubs never target OUTSIDE the leaf ring
export const HUB_COLLIDE_STRENGTH = 0.8; // how hard the collide force resolves overlap per tick

/** Degree → "how much of a hub is this". 0 for a leaf (degree ≤ 1), growing with √degree, so the
 *  hub forces leave low-degree nodes alone and act only on the genuinely-connected ones. */
export function hubFactor(degree: number): number {
  return Math.max(0, Math.sqrt(degree) - 1);
}
// DEFAULT for the live "Spread radius" slider (knowledge-graph-prefs.radialRing). Sets how
// far the outermost (least-connected / disconnected) ring sits; scaled by √(node count) by
// the engine. Lower = pulls strays inward; higher = pushes them out.
export const RADIAL_RING = 35;

// Simulation cooling, switched per update kind (see GraphCanvasEngine.setData). graphData
// always restarts the sim at alpha=1 and there's no public way to start gentler, so we
// control how much MOTION that energy produces via decay instead:
//  - STRUCTURAL (initial load / reload / reconcile / filter): d3 defaults → full energy
//    so charge can spread the whole graph out (no cramping).
//  - DELTA (live node/edge add): heavy velocity damping + fast alpha decay so the
//    established layout only drifts slightly while the new nodes settle in locally.
export const VELOCITY_DECAY_DEFAULT = 0.4; // d3 default
export const ALPHA_DECAY_DEFAULT = 0.0228; // d3 default (~300 ticks to cool)
export const VELOCITY_DECAY_DELTA = 0.8; // only 20% of velocity carries → small, gentle steps
export const ALPHA_DECAY_DELTA = 0.08; // cools in ~70 ticks → brief, local settle

/**
 * A d3-force implementing "most-connected in the middle, others around it": each node is
 * pulled toward a ring whose radius encodes its connectivity (`n.__targetR`, assigned
 * per-node by the engine from its degree) — hubs target the centre, leaf/orphan nodes
 * target the outer ring, so the graph self-organizes around its busiest nodes instead of
 * drifting into a blob. Written inline to avoid a d3-force import; d3 calls force(alpha)
 * each tick and force.initialize(nodes) on bind. Replaces the old origin-only gravity.
 */
export function degreeRadial(strength: number) {
  let simNodes: FgNode[] = [];
  const force = (alpha: number) => {
    for (const n of simNodes) {
      const r = Math.hypot(n.x ?? 0, n.y ?? 0);
      if (r < 1e-6) continue; // sitting at the origin: let charge nudge it out first
      // <0 pulls the node inward toward its ring, >0 pushes it outward.
      const k = (((n.__targetR ?? 0) - r) / r) * strength * alpha;
      n.vx = (n.vx ?? 0) + (n.x ?? 0) * k;
      n.vy = (n.vy ?? 0) + (n.y ?? 0) * k;
    }
  };
  force.initialize = (nodes: FgNode[]) => {
    simNodes = nodes;
  };
  return force;
}

/**
 * Per-node charge strength for the d3 many-body force, scaled so hubs repel harder.
 * `base` is the (negative) "Node repulsion" slider value; the multiplier is 1 at hubSep=0
 * (→ base, unchanged) and grows with √degree up to HUB_CHARGE_MULT_MAX. NODE_RADIUS import
 * isn't needed here — charge is dimensionless strength, not a radius.
 */
export function hubChargeStrength(degree: number, base: number, hubSep: number): number {
  if (hubSep <= 0) return base;
  const mult = Math.min(HUB_CHARGE_MULT_MAX, 1 + hubSep * HUB_CHARGE_GAIN * hubFactor(degree));
  return base * mult;
}

/**
 * Collision radius for a node: its drawn disc plus a hub bubble that grows with degree AND the
 * "Hub spacing" multiplier (the bubble IS the minimum hub-to-hub distance, so spacing is the
 * direct "how far" control). Returns 0 when hubSep=0 (or for leaves) so degreeCollide skips the
 * node. `nodeRadius` is passed in (the engine's NODE_RADIUS) to avoid a config import cycle.
 */
export function hubCollideRadius(
  degree: number,
  hubSep: number,
  hubSpacing: number,
  nodeRadius: number
): number {
  if (hubSep <= 0) return 0;
  const extra = hubSep * HUB_COLLIDE_GAIN * hubSpacing * hubFactor(degree);
  return extra > 0 ? nodeRadius + extra : 0; // leaves (factor 0) → 0 → skipped by the force
}

/** distanceMax for the many-body force, widened with hubSep × spacing so the stronger hub
 *  repulsion actually reaches neighbouring hubs even when they're pushed far apart (un-widened it
 *  would be clipped at the old cap and hubs past it would feel zero push). */
export function hubDistanceMax(base: number, hubSep: number, hubSpacing: number): number {
  return base * (1 + Math.max(0, hubSep) * HUB_DISTANCE_GAIN * Math.max(1, hubSpacing));
}

/**
 * An inline collision force (no d3-force dependency — the bundle doesn't re-export it) that
 * keeps each node's `__collideR` bubble from overlapping its neighbours, mirroring d3.forceCollide:
 * it nudges the projected next position (x+vx, y+vy) apart by velocity, weighting the push by each
 * node's radius². Nodes with `__collideR <= 0` (hub separation off, or leaves) don't participate, so
 * at hubSep=0 this is inert. O(n²) per tick, fine for this corpus's node counts; only hubs carry a
 * non-trivial radius so most pairs are skipped immediately.
 */
export function degreeCollide(strength = HUB_COLLIDE_STRENGTH) {
  let simNodes: FgNode[] = [];
  const force = () => {
    const n = simNodes.length;
    for (let i = 0; i < n; i++) {
      const a = simNodes[i];
      const ri = a.__collideR ?? 0;
      if (ri <= 0) continue;
      const xi = (a.x ?? 0) + (a.vx ?? 0);
      const yi = (a.y ?? 0) + (a.vy ?? 0);
      for (let j = i + 1; j < n; j++) {
        const b = simNodes[j];
        const rj = b.__collideR ?? 0;
        if (rj <= 0) continue;
        let x = xi - ((b.x ?? 0) + (b.vx ?? 0));
        let y = yi - ((b.y ?? 0) + (b.vy ?? 0));
        let l = x * x + y * y;
        const r = ri + rj;
        if (l >= r * r) continue; // no overlap
        if (l === 0) {
          // Coincident centres — jitter so the push has a direction (matches seedNewNodePositions).
          x = (Math.random() - 0.5) * 1e-3;
          y = (Math.random() - 0.5) * 1e-3;
          l = x * x + y * y;
        }
        l = Math.sqrt(l);
        const push = ((r - l) / l) * strength;
        const xl = x * push;
        const yl = y * push;
        // Heavier node (bigger bubble) moves less: distribute by the OTHER node's radius² share.
        const wj = (rj * rj) / (ri * ri + rj * rj);
        a.vx = (a.vx ?? 0) + xl * wj;
        a.vy = (a.vy ?? 0) + yl * wj;
        b.vx = (b.vx ?? 0) - xl * (1 - wj);
        b.vy = (b.vy ?? 0) - yl * (1 - wj);
      }
    }
  };
  force.initialize = (nodes: FgNode[]) => {
    simNodes = nodes;
  };
  return force;
}
