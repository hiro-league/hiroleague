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
