/**
 * d3-force tuning constants + the custom degree-radial centrality force for the knowledge
 * graph layout. These override force-graph's d3-force defaults.
 *
 * ⚠️ SCALE TARGET — this is NOT a toy graph. Production knowledge graphs are LARGE: tens of
 * thousands of nodes (target ~10k–50k+, growing). Scalability is the FIRST constraint, ahead of
 * visual polish. Every force must stay near-linear:
 *   - charge (many-body) and links → force-graph runs these on a quadtree / per-edge: OK at scale.
 *   - degreeRadial → O(n) single pass: OK.
 *   - collision → the quadtree `forceCollide` from `d3-force-3d` (O(n log n)), registered in
 *     graph-canvas-engine.ts. (Replaced a hand-rolled O(n²) collide that was fatal at scale.)
 *
 * The value sets below are REFERENCE FEEL tuned against a small (~50-node) dev corpus — a starting
 * point, NOT a scale ceiling. Expect to re-tune (and likely auto-scale by node count) for real sizes.
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

// Baseline (always-on) anti-overlap: every node claims a collision bubble equal to its DRAWN
// disc radius plus this pad, regardless of hub separation. Charge is center-to-center and
// radius-blind, so growing the node-size sliders used to make discs visually overlap at unchanged
// center spacing; this is the short-range geometric floor that fixes that without touching
// repulsion. It self-scales with node size (the Node size min/max sliders drive radiusForDegree),
// so there's no separate slider — COLLIDE_PAD is just the minimum visible gap between two discs.
export const COLLIDE_PAD = 2;

// Default for the live "Collision spacing" slider (knowledge-graph-prefs.collideScale). A global
// multiplier on EVERY node's collision radius (baseline + any hub bubble): 1 = normal, 1.5 = +50%
// personal space, 2 = double. Experiment knob for keeping node LABELS from covering neighbours —
// collision is a CIRCLE around the node centre while a title is wide text, so this spaces neighbours
// uniformly (helps crowding; won't perfectly clear a long title off to the side).
export const COLLIDE_SCALE_DEFAULT = 1;

// Defaults for the live "Node fade" controls. opacity = smoothstep(importance + zoomReveal; start,
// full). importance is 0..1 log-degree (degreeImportance); zoomReveal lifts clarity as you zoom in
// (see nodeFadeAlpha). "Node fade" range [start, full] = which nodes are faded when fully zoomed out;
// start = full = 0 → the whole effect is OFF (all solid). "Zoom reveal" range [lo, hi] is in ZOOM
// units: hazy below lo× → clear above hi×; hi ≤ lo → static (no zoom motion, just the importance fade).
export const NODE_FADE_START_DEFAULT = 0;
export const NODE_FADE_FULL_DEFAULT = 0;
export const NODE_REVEAL_LO_DEFAULT = 0.4; // at/below this zoom → maximum haze (only important nodes clear)
export const NODE_REVEAL_HI_DEFAULT = 2.5; // at/above this zoom → fully revealed (everything solid)

// ── Hub separation (the "Hub separation" slider, 0 = off) ─────────────────────────────────
// Goal: pull high-degree hubs apart from EACH OTHER so a dense graph doesn't read as one
// clump. Three coupled effects, ALL scaled by `hubSep` so hubSep=0 reproduces today's layout
// exactly (multiplier 1 / radius 0 / band 0):
//   1. charge ∝ √degree   — hubs repel everything (incl. other hubs) harder           (long range)
//   2. collide ∝ √degree  — each hub gets EXTRA personal-space reach on top of the always-on
//                           baseline disc collision (see COLLIDE_PAD / collideRadius)    (short range)
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
export const HUB_COLLIDE_STRENGTH = 0.3; // forceCollide push strength per pass (0..1); soft + iterations = gentle convergence (no jiggle)
export const COLLIDE_ITERATIONS = 5; // forceCollide resolution passes per tick; more passes clear overlap within fewer ticks

/** Degree → "how much of a hub is this". 0 for a leaf (degree ≤ 1), growing with √degree, so the
 *  hub forces leave low-degree nodes alone and act only on the genuinely-connected ones. */
export function hubFactor(degree: number): number {
  return Math.max(0, Math.sqrt(degree) - 1);
}
// DEFAULT for the live "Spread radius" slider (knowledge-graph-prefs.radialRing). Sets how
// far the outermost (least-connected / disconnected) ring sits; scaled by √(node count) by
// the engine. Lower = pulls strays inward; higher = pushes them out.
export const RADIAL_RING = 35;

// ── Simulation cooling per transition type — the "transition smoothness" knobs ────────────────
// Every transition restarts the sim at alpha=1. force-graph exposes NO custom-alpha and NO
// alphaTarget setter (verified against force-graph.d.ts: only d3VelocityDecay / d3AlphaDecay /
// d3AlphaMin / cooldownTicks / d3ReheatSimulation), and it doesn't hand out the simulation object.
// So a "gentler reheat" can't be done by injecting less energy — it's done by controlling how much
// of the alpha=1 burst reaches the screen and for how long. Three knobs, set per-transition right
// BEFORE the reheat:
//   • velocityDecay  — friction (0..1). HIGH (→1) throttles the burst on the FIRST tick → small,
//                      smooth move; LOW (→0) lets nodes fly and ring. The dominant "how strong" knob.
//   • alphaDecay     — how fast the sim cools (>0). HIGH = motion ends sooner; LOW = longer glide.
//   • cooldownTicks  — HARD tick cap; the sim freezes after N ticks no matter what. Bluntest "stop
//                      wiggling now" lever (force-graph default Infinity = run until alphaMin).
// Three profiles for the three transition kinds:
//   SPREAD — full relayout (initial load / reload / filter / "respread"): wants energy to lay out.
//            NOTE: hide/show goes through the structural path, so SPREAD also governs filter feel —
//            tuning SPREAD changes both initial-load and hide/show. (Splitting filter onto its own
//            profile would be a further step — that's the deferred "localized hide/show".)
//   TWEAK  — a physics-slider change on an already-settled graph (setForces): wants a gentle ease.
//            Previously inherited whatever profile the last data op left → now its own knobs.
//   DELTA  — a live node/edge add (ingest): established graph barely moves, new region settles.
export const VELOCITY_DECAY_SPREAD = 0.5; // (baseline was 0.4 - keep as reference) d3 default; full energy so charge spreads the graph
export const ALPHA_DECAY_SPREAD = 0.0228; // d3 default (~300 ticks to cool)
export const COOLDOWN_TICKS_SPREAD = Infinity; // run to natural settle (no cap)

export const VELOCITY_DECAY_TWEAK = 0.6; // ↑friction vs SPREAD so a slider nudge eases, not jolts
export const ALPHA_DECAY_TWEAK = 0.045; // (default was 0.05 keep for reference) ~90 ticks → quick settle after a param change
export const COOLDOWN_TICKS_TWEAK = 120; // hard stop so a tweak can't keep wandering for the full 15s

export const VELOCITY_DECAY_DELTA = 0.8; // only 20% of velocity carries → small, gentle steps
export const ALPHA_DECAY_DELTA = 0.08; // cools in ~70 ticks → brief, local settle
export const COOLDOWN_TICKS_DELTA = 90; // local add stops promptly (rarely bites at this decay)

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
 * Collision radius for a node, in two layers:
 *   1. baseline (always on) = drawn disc radius + COLLIDE_PAD, for EVERY node regardless of hub
 *      separation — this is what stops discs visually overlapping when node sizing grows them.
 *   2. hub bubble (only when hubSep>0, only genuine hubs) = an EXTRA reach that grows with degree
 *      and the "Hub spacing" multiplier (the bubble IS the minimum hub-to-hub distance, so spacing
 *      is the direct "how far" control), added ON TOP of the baseline.
 * Always > 0, so degreeCollide runs over every node now (was inert at hubSep=0). `nodeRadius` is
 * passed in (the engine's degree-based drawn radius) to avoid a config import cycle.
 */
export function collideRadius(
  degree: number,
  hubSep: number,
  hubSpacing: number,
  nodeRadius: number,
  collideScale: number
): number {
  const baseline = nodeRadius + COLLIDE_PAD; // always-on floor: discs never overlap
  const extra = hubSep <= 0 ? 0 : hubSep * HUB_COLLIDE_GAIN * hubSpacing * hubFactor(degree); // leaves (factor 0) → 0
  return (baseline + extra) * collideScale; // collideScale = live "Collision spacing" slider (1 = normal)
}

/** Cubic smoothstep of x, clamped to 0..1. */
function smoothstep01(x: number): number {
  const t = Math.min(1, Math.max(0, x));
  return t * t * (3 - 2 * t);
}

/**
 * Level-of-detail node opacity. opacity = smoothstep(importance + zoomReveal; fadeStart, fadeFull),
 * where zoomReveal = smoothstep(zoom; revealLo, revealHi) ∈ [0,1] LIFTS every node's clarity as you
 * zoom IN: below revealLo (far) reveal = 0 → only high-importance nodes clear; above revealHi (near)
 * reveal = 1 → importance + 1 pushes everything solid; between, lower-importance nodes resolve in
 * order. The [fadeStart, fadeFull] band stays fixed — zoom slides nodes THROUGH it (no collapse).
 * revealHi ≤ revealLo → static (no zoom motion). fadeFull ≤ fadeStart → whole effect off (all solid).
 */
export function nodeFadeAlpha(
  importance: number,
  zoom: number,
  fadeStart: number,
  fadeFull: number,
  revealLo: number,
  revealHi: number
): number {
  if (fadeFull <= fadeStart) return 1; // disabled / degenerate range → no fade (all solid)
  const reveal = revealHi <= revealLo ? 0 : smoothstep01((zoom - revealLo) / (revealHi - revealLo));
  return smoothstep01((importance + reveal - fadeStart) / (fadeFull - fadeStart));
}

/**
 * Node "importance" in 0..1 from its degree: log(1+degree) / log(1+maxDegree). Log (not √, not linear)
 * because real knowledge graphs are heavy-tailed — a few mega-hubs (200–300 links) over a long low-
 * degree tail; √-by-max crushed that tail into ~[0, 0.2]. Plain log (NOT min-max) so the least-
 * connected node still gets a NONZERO, controllable importance (a degree-1 node ≈ 0.12, not 0), which
 * is what lets the "Node fade" slider reveal small nodes. Used for the fade ONLY — node SIZE keeps √.
 */
export function degreeImportance(degree: number, degreeMax: number): number {
  const hi = Math.log1p(Math.max(0, degreeMax));
  if (hi <= 0) return 0; // empty / single isolated node → no spread
  return Math.min(1, Math.max(0, Math.log1p(Math.max(0, degree)) / hi));
}

/** distanceMax for the many-body force, widened with hubSep × spacing so the stronger hub
 *  repulsion actually reaches neighbouring hubs even when they're pushed far apart (un-widened it
 *  would be clipped at the old cap and hubs past it would feel zero push). */
export function hubDistanceMax(base: number, hubSep: number, hubSpacing: number): number {
  return base * (1 + Math.max(0, hubSep) * HUB_DISTANCE_GAIN * Math.max(1, hubSpacing));
}

// Collision is no longer hand-rolled here. It was an O(n²) brute-force copy of d3.forceCollide
// (jiggly + fatal at scale); the engine now registers the quadtree `forceCollide` from `d3-force-3d`
// (O(n log n)) directly, driven by HUB_COLLIDE_STRENGTH / COLLIDE_ITERATIONS and the per-node
// `__collideR` (collideRadius) as its `.radius(...)` accessor. See graph-canvas-engine.ts.
