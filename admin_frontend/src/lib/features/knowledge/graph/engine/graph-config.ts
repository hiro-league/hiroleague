/**
 * Rendering / layout tuning constants for the knowledge graph canvas engine.
 *
 * These are graph-space units (canvas → screen via globalScale) and animation timings.
 * d3-force simulation knobs live in graph-forces.ts; colours in graph-scheme.ts.
 * Tweak any of these and Vite HMR reflects the change instantly.
 */

/** How long a freshly-created node/edge glows after appearing (ms). Shared with the model
 *  (recent[] glow map) so the fade window and the pruning window agree. */
export const GLOW_MS = 3000;

/** Node disc radius (graph-space units); also force-graph's nodeRelSize so the default
 *  hit-test region matches the drawn disc. */
export const NODE_RADIUS = 10;

/** zoomToFit camera-animation duration (ms). */
export const FIT_ANIM_MS = 450;

// ── Zoom-gated label sizing: per-type min/max font size mapped to min/max zoom ──
// At zoom <= ZOOM_MIN the label is HIDDEN; at ZOOM_MIN it renders at FONT_MIN on-screen
// px; at >= ZOOM_MAX it clamps to FONT_MAX; linear interpolation in between (see
// labelFontSize in graph-draw.ts, which converts to canvas-space by dividing by scale).
export const NODE_ZOOM_MIN = 1.0;
export const NODE_ZOOM_MAX = 2.5;
export const NODE_FONT_MIN = 8;
export const NODE_FONT_MAX = 16;

export const EDGE_ZOOM_MIN = 1.0;
export const EDGE_ZOOM_MAX = 2.5;
export const EDGE_FONT_MIN = 8;
export const EDGE_FONT_MAX = 14;

// ── Node-name wrapping (see wrapLabel in graph-draw.ts) ──
export const NODE_LABEL_WRAP = 12;
export const NODE_LABEL_MAX_LINES = 3;

// ── Parallel-edge & self-loop curvature (see assignLinkCurvatures in graph-links.ts) ──
export const SELF_LOOP_BASE = 0.4; // first self-loop curvature; extra loops step out
export const SELF_LOOP_STEP = 0.3;
