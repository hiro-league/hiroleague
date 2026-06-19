/**
 * GraphCanvasEngine — framework-agnostic wrapper around the `force-graph` instance for
 * the knowledge graph view. Owns the canvas lifecycle, the force simulation, custom
 * node/link drawing, camera arbitration, and redraw gating. KnowledgeGraphPanel drives it
 * imperatively: it pushes reactive model reads in via setData/setForces/setSearch/etc.,
 * and the engine keeps its own PLAIN (non-reactive) state so the draw callbacks never
 * touch Svelte proxies.
 *
 * ── The mirror-object problem (the core fix) ────────────────────────────────────────────
 * force-graph / d3 store live simulation state (x, y, vx, vy, fx, fy, index) directly on
 * the node/link objects we hand them. Those objects MUST keep a stable identity and
 * persist across deltas. We CANNOT feed force-graph the model's Svelte $state objects:
 * every model rebuild (`nodes = [...nodeById.values()]`) makes Svelte create FRESH proxies,
 * and the $state set-trap stores writes in signals — never on the raw target — so each
 * fresh proxy reads x/y back as `undefined`, and d3 re-initialises every node to a spiral
 * position (the "the whole graph resets on every update" bug). Instead the engine keeps its
 * own plain mirror objects (fgNodeById / fgLinkById), reconciled by id on each update:
 * existing ids reuse their mirror (positions preserved), new ids get a fresh mirror,
 * removed ids are dropped.
 */
import type ForceGraph from 'force-graph';
import { forceCollide } from 'd3-force-3d'; // quadtree collision (O(n log n)) — the lib force-graph already uses
import { colorFor, humanizeRelType } from '../knowledge-graph-style';
import type { SearchFocusMode } from '../knowledge-graph-prefs';
import {
  EDGE_FONT_MAX,
  EDGE_FONT_MIN,
  EDGE_ZOOM_MAX,
  EDGE_ZOOM_MIN,
  FIT_ANIM_MS,
  GLOW_MS,
  NODE_FONT_MAX,
  NODE_FONT_MIN,
  NODE_RADIUS,
  NODE_ZOOM_MAX,
  NODE_ZOOM_MIN
} from './graph-config';
import { drawIcon, drawTextPill, labelFontSize, wrapLabel } from './graph-draw';
import {
  ALPHA_DECAY_SPREAD,
  ALPHA_DECAY_TWEAK,
  ALPHA_DECAY_DELTA,
  CHARGE_DISTANCE_MAX,
  CHARGE_STRENGTH,
  COLLIDE_ITERATIONS,
  COLLIDE_SCALE_DEFAULT,
  NODE_FADE_START_DEFAULT,
  NODE_FADE_FULL_DEFAULT,
  NODE_REVEAL_LO_DEFAULT,
  NODE_REVEAL_HI_DEFAULT,
  nodeFadeAlpha,
  degreeImportance,
  COOLDOWN_TICKS_SPREAD,
  COOLDOWN_TICKS_TWEAK,
  COOLDOWN_TICKS_DELTA,
  degreeRadial,
  GRAVITY_STRENGTH,
  HUB_BAND_FRACTION,
  HUB_BAND_FRACTION_MAX,
  HUB_COLLIDE_STRENGTH,
  collideRadius,
  hubChargeStrength,
  hubDistanceMax,
  RADIAL_STRENGTH,
  VELOCITY_DECAY_SPREAD,
  VELOCITY_DECAY_TWEAK,
  VELOCITY_DECAY_DELTA
} from './graph-forces';
import { assignLinkCurvatures } from './graph-links';
import { computeScheme, type Scheme } from './graph-scheme';
import { linkEndId, type FgLink, type FgNode } from './graph-types';

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
  /** Bi-temporal markers; an edge is "invalid" (superseded) when either is set. */
  invalid_at?: string | null;
  expired_at?: string | null;
  /** Synthetic aggregate edge (see collapseParallelLinks) + the ids it folds. `whole` = it stands in
   *  for ALL the pair's relations ("X relations"), else it's the leftover ("N other relations"). */
  aggregate?: boolean;
  collapsedIds?: string[];
  whole?: boolean;
}

/** Neighbor focus: when a node is SELECTED (and no search is active), fade/hide everything
 *  outside its ego network. Renderer-only (no relayout) so clicking around stays snappy. */
export interface NeighborFocusState {
  active: boolean;
  // 'none' = the selection's ego set is known (so the fade can keep it solid) but the rest is NOT
  // dimmed/hidden — used by selectionFocusMode 'all'. 'dim'/'hide' also apply the focus treatment.
  mode: 'dim' | 'hide' | 'none';
  selectedId: string;
  nodeIds: Set<string>;
  edgeIds: Set<string>;
}

export interface GraphCanvasCallbacks {
  onNodeClick: (id: string) => void;
  onLinkClick: (id: string) => void;
  onBackgroundClick: () => void;
  /** Current canvas zoom scale (force-graph transform.k), on every pan/zoom + programmatic fit.
   *  Surfaced in the stats overlay to help tune the zoom-threshold sliders (edge/node labels). */
  onZoomChange?: (k: number) => void;
}

/** Our concrete force-graph instance type — the shipped generic class specialized to our
 *  mirror node/link shapes, so every fluent call + accessor is fully type-checked. */
type FgInstance = ForceGraph<FgNode, FgLink>;

/** Structural signals: identity-compared against the previous update to decide whether
 *  this is a full relayout (load/reload/reconcile/filter) or an incremental live delta. */
export interface StructuralContext {
  loadVersion: number;
  hiddenNodeIds: Set<string>;
  hiddenEdgeTypes: Set<string>;
  /** Edge-filter token (validity / date ranges / max-connections) — changes force a relayout. */
  filterToken: string;
}

export interface SearchState {
  searchActive: boolean;
  matchedNodeIds: Set<string>;
  matchedEdgeIds: Set<string>;
  /** Matched nodes + endpoints of matched edges, to frame on a search. Null when inactive. */
  focusNodeIds: Set<string> | null;
  searchFocusMode: SearchFocusMode;
}

/** Aggregate-edge label: "X relations" when it folds the WHOLE pair (max visible edges = 1), else
 *  "N other relations" when one or more real edges are shown alongside it. */
function aggregateLabel(l: FgLink): string {
  const n = l.collapsedIds?.length ?? 0;
  return l.whole ? `${n} relations` : `${n} other relations`;
}

/** Below this "Node fade" opacity a node is treated as gone: skipped from drawing AND non-interactive. */
const FADE_CULL_EPSILON = 0.012;

/** Multiply the alpha channel of an `rgba()`/`rgb()` colour by `factor` (clamped 0..1). Non-rgba
 *  strings (hex, named) are returned unchanged — only the scheme's rgba link colours get scaled. */
function scaleColorAlpha(color: string, factor: number): string {
  if (factor >= 1) return color;
  const m = color.match(/^rgba?\(([^)]+)\)$/i);
  if (!m) return color;
  const p = m[1].split(',').map((s) => s.trim());
  if (p.length < 3) return color;
  const a = p.length >= 4 ? parseFloat(p[3]) : 1;
  return `rgba(${p[0]},${p[1]},${p[2]},${Math.max(0, Math.min(1, a * factor))})`;
}

export class GraphCanvasEngine {
  private readonly callbacks: GraphCanvasCallbacks;
  private container: HTMLDivElement | null = null;
  private fg: FgInstance | null = null;
  // The quadtree collision force (d3-force-3d). Held so we can refresh its CACHED per-node radii:
  // forceCollide reads `.radius(...)` only at initialize, not per tick — unlike the old live-reading
  // custom force — so sizing/hub changes that don't reset graphData must re-push the radii (syncCollideRadii).
  private collideForce: ReturnType<typeof forceCollide<FgNode>> | null = null;

  // ── force-graph mirror objects (see class header). Existing mirrors keep identity → x/y. ──
  private readonly fgNodeById = new Map<string, FgNode>();
  private readonly fgLinkById = new Map<string, FgLink>();
  private prevLoadVersion = -1;
  private prevHiddenNodes: Set<string> | null = null;
  private prevHiddenEdges: Set<string> | null = null;
  private prevFilterToken: string | null = null;

  // Set on a relayout so the next engine-stop can reframe the SEARCH subset (onEngineStop). It no
  // longer triggers a whole-graph zoom-to-fit on load/reload/filter — that snap was unwanted.
  private fitPending = false;

  // ── Camera ownership ──────────────────────────────────────────────────────────────────
  // Auto zoom-to-fit otherwise fights the user: while physics settle (initial load, live
  // deltas) onEngineStop kept re-firing zoomToFit and snapping the camera back. Once the
  // user moves the camera by hand we stop auto-fitting; reset on intentional reframes.
  private userMovedCamera = false;
  // True only while one of OUR programmatic fits is animating, so onZoom doesn't mistake an
  // automatic fit for a user gesture. Starts true so force-graph's initial auto-centring
  // isn't counted as a user move.
  private programmaticZoom = true;
  private programmaticZoomTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Live (plain) state read by the draw callbacks ──
  private scheme: Scheme = computeScheme();
  private recent: Record<string, number> = {};
  private search: SearchState = {
    searchActive: false,
    matchedNodeIds: new Set(),
    matchedEdgeIds: new Set(),
    focusNodeIds: null,
    searchFocusMode: 'highlight'
  };
  // Neighbor focus (selected node's ego network). Lower priority than search — applied only
  // while no search is active (decision: search wins). Renderer-only; no relayout.
  private neighborFocus: NeighborFocusState = {
    active: false,
    mode: 'dim',
    selectedId: '',
    nodeIds: new Set(),
    edgeIds: new Set()
  };
  // The currently-selected node/edge (the one whose detail panel is open). Drawn with a blue
  // ring/line that overrides the amber search highlight. Null when nothing is selected.
  private selected: { kind: 'node' | 'edge'; id: string } | null = null;
  // Transient hover-preview from the detail panel's Connections list (ring without selecting).
  // previewNodeIds = the previewed node, OR a previewed edge's two endpoints. Renderer-only.
  private preview: { kind: 'node' | 'edge'; id: string } | null = null;
  private previewNodeIds = new Set<string>();
  private curveAmount = 0.45;
  // Live force params owned here so the draw/layout code reads plain values, not Svelte
  // proxies. Seeded in mount() from the persisted "Center pull"/"Spread radius" sliders.
  private centerStrength = 0.05; // d3 center-force strength (pull-to-middle for ALL nodes)
  private radialRing = 90; // outer-ring radius for degreeRadial; used by setData's outerRing
  // Live "Hub separation" slider (0 = off → layout identical to before this feature). Scales the
  // per-node charge/collide forces + the degreeRadial inner band by node degree (see graph-forces).
  private hubSeparation = 0;
  // Live "Hub spacing" slider (multiplier ≥ 0; default 1). HOW FAR hubs settle apart — scales the
  // collide bubble, the charge distanceMax reach, and the inner band. Inert while hubSeparation = 0.
  private hubSpacing = 1;
  // Live "Collision spacing" slider (multiplier; default 1). Scales EVERY node's collide radius, to
  // open extra room so node labels don't cover neighbours. Fed into collideRadius (see graph-forces).
  private collideScale = COLLIDE_SCALE_DEFAULT;
  // Base charge ("Node repulsion" slider value, negative); seeded from CHARGE_STRENGTH and updated
  // by setForces. Kept so retargets can rebuild the per-node charge accessor with the current base.
  private chargeStrength = CHARGE_STRENGTH;
  // Degree-based node sizing (View → "Node size" range): radiusForDegree maps a node's __degree to a
  // radius in [nodeSizeMin, nodeSizeMax] via √degree against the current max degree. Equal min/max =
  // flat (all nodes the same). Seeded in mount() from the persisted slider.
  private nodeSizeMin = NODE_RADIUS;
  private nodeSizeMax = NODE_RADIUS;
  private degreeMax = 1; // largest __degree in the current set; refreshed with the degree map
  // Denoise: node ids to render-DIM (low-connection 'dim' mode). Render-only; the structural
  // hide/only modes are handled upstream in the model's visibleNodes, so they never reach here.
  private denoiseDimIds = new Set<string>();
  // Live label sizing (View → font controls), seeded from graph-config defaults; the "Edge label
  // max" trims relation labels to this many characters. Updated via setLabelSizing().
  private edgeZoomMin = EDGE_ZOOM_MIN;
  private edgeZoomMax = EDGE_ZOOM_MAX;
  private edgeFontMin = EDGE_FONT_MIN;
  private edgeFontMax = EDGE_FONT_MAX;
  private nodeZoomMin = NODE_ZOOM_MIN;
  private nodeZoomMax = NODE_ZOOM_MAX;
  private nodeFontMin = NODE_FONT_MIN;
  private nodeFontMax = NODE_FONT_MAX;
  private edgeLabelMax = 22;
  // Live "Node fade" range (View). Opacity = smoothstep(importance; thresholds shifted by zoom) — see
  // nodeFadeAlpha. Render-only (setNodeFade → keepRedrawing). start = full = 0 disables it (all solid).
  private nodeFadeStart = NODE_FADE_START_DEFAULT;
  private nodeFadeFull = NODE_FADE_FULL_DEFAULT;
  // "Zoom reveal" range (ZOOM units): hazy below Lo× → clear above Hi×. Lifts node clarity as you
  // zoom in (level-of-detail). Hi ≤ Lo → static (importance-only fade, no zoom motion).
  private nodeRevealLo = NODE_REVEAL_LO_DEFAULT;
  private nodeRevealHi = NODE_REVEAL_HI_DEFAULT;
  private currentZoom = 1; // live canvas zoom (transform.k), kept for accessors that get no scale arg

  // ── Redraw gating ──────────────────────────────────────────────────────────────────────
  // force-graph's autoPauseRedraw lets the canvas idle once the sim settles. We keep it on
  // and only kick frames for our own animations (glow fade) and one-off updates (theme).
  private redrawUntil = 0;
  private redrawTimer: ReturnType<typeof setTimeout> | null = null;

  private themeObserver: MutationObserver | null = null;

  constructor(callbacks: GraphCanvasCallbacks) {
    this.callbacks = callbacks;
  }

  /** Create the force-graph instance, configure forces + callbacks, and start observing
   *  the theme. Dynamic-imports force-graph (browser-only; this also runs during SSR). */
  async mount(
    container: HTMLDivElement,
    initial: {
      linkStrength: number;
      linkDistance: number;
      curveAmount: number;
      centerStrength: number;
      radialRing: number;
      hubSeparation: number;
      hubSpacing: number;
      collideScale: number;
      nodeSizeMin: number;
      nodeSizeMax: number;
    }
  ): Promise<void> {
    this.container = container;
    this.curveAmount = initial.curveAmount;
    this.centerStrength = initial.centerStrength;
    this.radialRing = initial.radialRing;
    this.hubSeparation = initial.hubSeparation;
    this.hubSpacing = initial.hubSpacing;
    this.collideScale = initial.collideScale;
    this.nodeSizeMin = initial.nodeSizeMin;
    this.nodeSizeMax = initial.nodeSizeMax;
    const { default: ForceGraphCtor } = await import('force-graph');
    // force-graph v1.51 ships as a class but still supports the legacy factory form
    // `ForceGraph()(container)` at runtime; cast to that factory shape (the class type
    // doesn't model it) and specialize the instance to our mirror node/link types.
    const factory = ForceGraphCtor as unknown as () => (el: HTMLElement) => FgInstance;
    const fg = factory()(container)
      .nodeId('id')
      // Tooltip on hover still useful for full type + name when the on-canvas label is truncated.
      .nodeLabel((n: FgNode) => `${n.name} · ${n.type}`)
      // Hover tooltip ONLY for edges whose on-canvas label was trimmed (humanized length exceeds
      // the edge-label-max) — shows the full relation. Non-truncated edges return '' (no tooltip).
      .linkLabel((l: FgLink) => {
        if (l.aggregate) return aggregateLabel(l);
        const human = humanizeRelType(l.rel_type);
        return human.length > this.edgeLabelMax ? human : '';
      })
      .nodeRelSize(NODE_RADIUS) // hit radius = √val · relSize; with nodeVal below this tracks the disc
      .nodeVal((n: FgNode) => this.nodeValFor(n)) // per-node val so the click area matches the drawn size
      .linkColor((l: FgLink) => this.linkColor(l))
      .linkWidth((l: FgLink) => this.linkWidth(l))
      // FIX (two-click edge selection): force-graph hit-tests links on a shadow canvas with a
      // hit area of linkWidth (~1.2) + linkHoverPrecision (default 4) ≈ 5.2 graph-units. The
      // relation label we draw is CENTERED on the line but its glyphs straddle it by several px,
      // so a click on the label landed OUTSIDE that thin band → resolved as a background click →
      // clearSelection() closed the open panel, forcing a second click. Widen the band so clicks
      // on the label (or near the line) reliably select the edge in one click. Kept modest so
      // edges passing near a node don't steal the node's own click.
      .linkHoverPrecision(8)
      // Parallel edges between the same pair fan into arcs (see assignLinkCurvatures).
      .linkCurvature((l: FgLink) => l.__curvature ?? 0)
      // Hide arrowheads of non-matching edges in "hide" focus (color/width alone leaves the
      // arrow glyph visible).
      .linkDirectionalArrowLength((l: FgLink) => {
        const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
        return off && mode === 'hide' ? 0 : 5;
      })
      .linkDirectionalArrowRelPos(0.92) // pull arrowhead inside the target disc
      .autoPauseRedraw(true) // PERF: idle when settled; we kick frames via keepRedrawing()
      .onNodeClick((n: FgNode) => this.callbacks.onNodeClick(n.id))
      // Aggregate ("N other relations") edges ARE selectable now: clicking one opens the detail
      // panel keyed by its synthetic id (KnowledgeGraphPanel resolves it to its folded edges).
      .onLinkClick((l: FgLink) => this.callbacks.onLinkClick(l.id))
      .onBackgroundClick(() => this.callbacks.onBackgroundClick())
      .nodeCanvasObjectMode(() => 'replace')
      .nodeCanvasObject((n: FgNode, ctx: CanvasRenderingContext2D, scale: number) =>
        this.drawNode(n, ctx, scale)
      )
      // Hit-area: paint the disc only when the node is visible enough; a "Node fade"-culled node
      // (opacity ≈ 0) paints nothing → non-interactive (no clicks/hover), matching what's drawn.
      .nodePointerAreaPaint((n: FgNode, color: string, ctx: CanvasRenderingContext2D, scale: number) =>
        this.paintNodePointerArea(n, color, ctx, scale)
      )
      .linkCanvasObjectMode(() => 'after')
      .linkCanvasObject((l: FgLink, ctx: CanvasRenderingContext2D, scale: number) =>
        this.drawLink(l, ctx, scale)
      );
    this.fg = fg;

    // d3-force tuning. Optional-chain the force getters because some forces are created
    // lazily; d3ReheatSimulation kicks the cooled sim so the params take effect.
    fg.d3Force('link')?.distance(initial.linkDistance).strength(initial.linkStrength);
    // Charge is now a per-node accessor so hubs repel harder ("Hub separation"); distanceMax
    // caps repulsion range (widened with the hub boost so it still reaches neighbouring hubs).
    // setForces overwrites these with the live slider values right after mount.
    fg.d3Force('charge')
      ?.strength((n: FgNode) => hubChargeStrength(n.__degree ?? 0, this.chargeStrength, this.hubSeparation))
      .distanceMax(hubDistanceMax(CHARGE_DISTANCE_MAX, this.hubSeparation, this.hubSpacing));
    fg.d3Force('center')?.strength(this.centerStrength); // live "Center pull" slider seed
    // Degree-based radial centrality (hubs centre, leaves out) — replaces plain gravity.
    void GRAVITY_STRENGTH; // retained for the tuning guide; radial uses RADIAL_STRENGTH
    fg.d3Force('gravity', degreeRadial(RADIAL_STRENGTH));
    // Collision: an always-on baseline bubble (drawn disc + pad) so nodes never visually overlap,
    // plus an extra hub bubble when "Hub separation" > 0. The baseline self-scales with node size,
    // so growing the size sliders can't make discs overlap (see collideRadius). Quadtree solver
    // (d3-force-3d) → O(n log n), scales to the real 10k–50k node target; `__collideR` is the
    // per-node radius (kept in sync by syncCollideRadii on sizing/hub changes that skip graphData).
    this.collideForce = forceCollide<FgNode>()
      .radius((n) => n.__collideR ?? 0)
      .strength(HUB_COLLIDE_STRENGTH)
      .iterations(COLLIDE_ITERATIONS);
    fg.d3Force('collide', this.collideForce);
    fg.onEngineStop(() => this.onEngineStop());
    // Detect a hand-driven pan/zoom so auto-fit yields to it (see userMovedCamera).
    fg.onZoom((t) => {
      if (!this.programmaticZoom) this.userMovedCamera = true;
      this.currentZoom = t.k; // for the edge fade (linkColor has no scale arg, unlike drawLink)
      this.callbacks.onZoomChange?.(t.k); // report live zoom (also fires on programmatic fits)
    });
    this.currentZoom = fg.zoom();
    this.callbacks.onZoomChange?.(fg.zoom()); // seed the initial level before any zoom event
    fg.d3ReheatSimulation?.();

    // Refresh the cached scheme + repaint once whenever the app toggles theme.
    this.scheme = computeScheme();
    if (typeof MutationObserver !== 'undefined') {
      this.themeObserver = new MutationObserver(() => {
        this.scheme = computeScheme();
        this.keepRedrawing(150); // a few frames so new colors paint even while idle
      });
      this.themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
      });
    }
    this.resize();
  }

  resize(): void {
    const fg = this.fg;
    if (fg && this.container) {
      fg.width(this.container.clientWidth).height(this.container.clientHeight);
    }
  }

  /** Reconcile the reactive render set into the mirrors and feed force-graph. Decides
   *  structural (full relayout + fit) vs incremental delta (local settle, camera held). */
  setData(rNodes: RenderNode[], rLinks: RenderLink[], ctx: StructuralContext): void {
    const fg = this.fg;
    if (!fg) return;

    // First paint = no mirrors yet. Structural reloads / filter changes also force relayout.
    const structural =
      ctx.loadVersion !== this.prevLoadVersion ||
      ctx.hiddenNodeIds !== this.prevHiddenNodes ||
      ctx.hiddenEdgeTypes !== this.prevHiddenEdges ||
      ctx.filterToken !== this.prevFilterToken ||
      this.fgNodeById.size === 0;
    this.prevLoadVersion = ctx.loadVersion;
    this.prevHiddenNodes = ctx.hiddenNodeIds;
    this.prevHiddenEdges = ctx.hiddenEdgeTypes;
    this.prevFilterToken = ctx.filterToken;

    const { fgNodes, fgLinks, freshNodeIds } = this.reconcile(rNodes, rLinks);

    // Degree-based radial targets for degreeRadial(): busiest node → centre (radius 0),
    // least-connected → outer ring, spacing scaled by √(node count). We gate only the RING
    // TARGETS on structural-vs-delta: recomputing them every delta makes outerRing (∝ √N)
    // grow each batch and yank the whole graph outward, so on a delta we leave existing
    // nodes' targets untouched and assign one only to the new arrivals.
    const degree = new Map<string, number>();
    for (const l of fgLinks) {
      const a = linkEndId(l.source);
      const b = linkEndId(l.target);
      degree.set(a, (degree.get(a) ?? 0) + 1);
      degree.set(b, (degree.get(b) ?? 0) + 1);
    }
    this.setDegreeRange(degree); // refresh degreeMax (sizing + fade importance)
    const maxDegree = this.degreeMax;
    const outerRing = this.radialRing * Math.max(1, Math.sqrt(fgNodes.length));
    assignLinkCurvatures(fgLinks, this.curveAmount); // fan out parallel edges before painting

    if (structural) {
      // Full relayout (reload / filter / first paint): retarget every node, full-energy
      // cooling so the whole graph spreads.
      for (const n of fgNodes) this.assignTarget(n, degree, maxDegree, outerRing);
      fg.d3VelocityDecay?.(VELOCITY_DECAY_SPREAD);
      fg.d3AlphaDecay?.(ALPHA_DECAY_SPREAD);
      fg.cooldownTicks?.(COOLDOWN_TICKS_SPREAD);
      fg.graphData({ nodes: fgNodes, links: fgLinks });
      // fitPending only drives the SEARCH-subset reframe on settle now (onEngineStop). We do NOT
      // auto zoom-to-fit the whole graph on load / reload / filter — that snap was unwanted; the
      // camera stays put unless the user hits "Fit to view" or runs a search.
      this.fitPending = true;
      fg.d3ReheatSimulation?.();
      return;
    }

    // Incremental live delta: existing mirrors already hold their positions, so the layout
    // stays put. Seed each NEW node near its already-placed neighbours (warm start), target
    // only the new nodes, then a damped, fast-cooling reheat settles the new region locally
    // without the established graph jumping. No zoom-to-fit so the camera holds.
    const fresh = new Set(freshNodeIds);
    const placed = new Map<string, FgNode>();
    for (const n of fgNodes) {
      if (!fresh.has(n.id) && n.x != null && n.y != null) placed.set(n.id, n);
    }
    const newNodes = fgNodes.filter((n) => fresh.has(n.id));
    for (const n of newNodes) this.assignTarget(n, degree, maxDegree, outerRing);
    this.seedNewNodePositions(newNodes, fgLinks, placed);
    fg.d3VelocityDecay?.(VELOCITY_DECAY_DELTA);
    fg.d3AlphaDecay?.(ALPHA_DECAY_DELTA);
    fg.cooldownTicks?.(COOLDOWN_TICKS_DELTA);
    fg.graphData({ nodes: fgNodes, links: fgLinks });
    this.fitPending = false; // don't snap the camera on live deltas
    fg.d3ReheatSimulation?.();
  }

  /** Layout-force sliders → d3 forces; reheat so the new params resolve on the existing
   *  layout. "Center pull" tightens the whole graph toward the middle (connectivity-blind →
   *  reels in disconnected strays/components); "Spread radius" moves the degree-radial outer
   *  ring (so it only needs a retarget when it actually changed). */
  setForces(opts: {
    linkStrength: number;
    linkDistance: number;
    centerStrength: number;
    radialRing: number;
    chargeStrength: number;
    hubSeparation: number;
    hubSpacing: number;
    collideScale: number;
  }): void {
    const fg = this.fg;
    if (!fg) return;
    fg.d3Force('link')?.strength(opts.linkStrength).distance(opts.linkDistance);
    fg.d3Force('center')?.strength(opts.centerStrength);
    this.centerStrength = opts.centerStrength;
    this.chargeStrength = opts.chargeStrength;
    const hubChanged =
      opts.hubSeparation !== this.hubSeparation || opts.hubSpacing !== this.hubSpacing;
    const collideScaleChanged = opts.collideScale !== this.collideScale;
    this.hubSeparation = opts.hubSeparation;
    this.hubSpacing = opts.hubSpacing;
    this.collideScale = opts.collideScale; // set BEFORE any recompute so collideRadius reads the new scale
    // Live "Node repulsion" × "Hub separation" × "Hub spacing": charge is a per-node accessor (hubs
    // repel harder by degree), and distanceMax widens with hubSep×spacing so the push still reaches
    // hubs even when spread far. Reheat re-initialises many-body, recomputing strengths from __degree.
    fg.d3Force('charge')
      ?.strength((n: FgNode) => hubChargeStrength(n.__degree ?? 0, this.chargeStrength, this.hubSeparation))
      .distanceMax(hubDistanceMax(CHARGE_DISTANCE_MAX, this.hubSeparation, this.hubSpacing));
    // The radial inner band AND every node's collide radius depend on hubSeparation, so a hub
    // change needs a full retarget too (not just a ring change). "Collision spacing" only affects
    // __collideR, so when it alone changes a lighter collide-radii recompute is enough.
    if (opts.radialRing !== this.radialRing || hubChanged) {
      this.radialRing = opts.radialRing;
      this.retargetAllNodes(); // recompute __targetR / __degree / __collideR (uses the new collideScale)
    } else if (collideScaleChanged) {
      this.recomputeCollideRadii(); // collideScale touches only the collide bubble
    }
    // A slider change on an already-settled graph wants to EASE to the new equilibrium, not relayout.
    // The reheat still goes to alpha=1 (no custom-alpha in force-graph), so the TWEAK profile damps
    // the burst (high velocityDecay) and caps the motion window (cooldownTicks) instead. Previously
    // this path set no cooling and inherited whatever the last setData left behind.
    fg.d3VelocityDecay?.(VELOCITY_DECAY_TWEAK);
    fg.d3AlphaDecay?.(ALPHA_DECAY_TWEAK);
    fg.cooldownTicks?.(COOLDOWN_TICKS_TWEAK);
    fg.d3ReheatSimulation?.();
  }

  /** Live label sizing (View → font controls) + edge-label trim length. Render-only: repaint
   *  once, no relayout. */
  setLabelSizing(opts: {
    edgeZoomMin: number;
    edgeZoomMax: number;
    edgeFontMin: number;
    edgeFontMax: number;
    nodeZoomMin: number;
    nodeZoomMax: number;
    nodeFontMin: number;
    nodeFontMax: number;
    edgeLabelMax: number;
  }): void {
    this.edgeZoomMin = opts.edgeZoomMin;
    this.edgeZoomMax = opts.edgeZoomMax;
    this.edgeFontMin = opts.edgeFontMin;
    this.edgeFontMax = opts.edgeFontMax;
    this.nodeZoomMin = opts.nodeZoomMin;
    this.nodeZoomMax = opts.nodeZoomMax;
    this.nodeFontMin = opts.nodeFontMin;
    this.nodeFontMax = opts.nodeFontMax;
    this.edgeLabelMax = opts.edgeLabelMax;
    this.keepRedrawing(120); // paint the new sizing even when the sim is idle
  }

  /** Live "Node fade" range (View → importance/zoom opacity). Render-only: store + repaint, no
   *  relayout. drawNode + paintNodePointerArea read these to fade (and cull) low-prominence nodes. */
  setNodeFade(opts: {
    nodeFadeStart: number;
    nodeFadeFull: number;
    nodeRevealLo: number;
    nodeRevealHi: number;
  }): void {
    this.nodeFadeStart = opts.nodeFadeStart;
    this.nodeFadeFull = opts.nodeFadeFull;
    this.nodeRevealLo = opts.nodeRevealLo;
    this.nodeRevealHi = opts.nodeRevealHi;
    this.keepRedrawing(120);
  }

  /** Degree-based node sizing (View → "Node size"). Render-only: refresh the hit-area accessor +
   *  the collide bubble base, then repaint. No relayout (the collide change settles on the next one). */
  setNodeSizing(opts: { minSize: number; maxSize: number }): void {
    this.nodeSizeMin = opts.minSize;
    this.nodeSizeMax = opts.maxSize;
    if (!this.fg) return;
    this.applyNodeVal(); // re-apply so force-graph recomputes cached node radii for hit-testing
    this.recomputeCollideRadii(); // collide bubble tracks the new drawn radius (baseline + any hub reach)
    this.keepRedrawing(150);
  }

  /** Render-only denoise: the set of low-connection node ids to fade ('dim' mode). Structural
   *  hide/only are applied upstream (model.visibleNodes), so this only ever carries the dim set. */
  setDenoiseDim(ids: Set<string>): void {
    this.denoiseDimIds = ids;
    this.keepRedrawing(200);
  }

  /** Refresh degreeMax for the current set (drives node sizing AND fade importance). */
  private setDegreeRange(degree: Map<string, number>): void {
    const vals = [...degree.values()];
    this.degreeMax = vals.length ? Math.max(1, ...vals) : 1;
  }

  /** Map a node's degree to its drawn radius in [nodeSizeMin, nodeSizeMax] via √degree against the
   *  current max degree. Equal min/max → flat (every node nodeSizeMin). */
  private radiusForDegree(degree: number): number {
    if (this.nodeSizeMax <= this.nodeSizeMin) return this.nodeSizeMin;
    const t = this.degreeMax > 0 ? Math.sqrt(Math.max(0, degree)) / Math.sqrt(this.degreeMax) : 0;
    return this.nodeSizeMin + t * (this.nodeSizeMax - this.nodeSizeMin);
  }

  /** force-graph node "val" so the pointer hit-area (√val · nodeRelSize) equals the drawn radius. */
  private nodeValFor(n: FgNode): number {
    const ratio = this.radiusForDegree(n.__degree ?? 0) / NODE_RADIUS;
    return ratio * ratio;
  }

  /** Node "importance" in 0..1 — MIN-MAX LOG of degree (see degreeImportance). Log-spread (not √)
   *  so a heavy-tailed graph (a few mega-hubs over a long low-degree tail) doesn't crush the whole
   *  tail into a sliver of the "Node fade" slider. Independent of the size sliders (degree, not radius). */
  private normDegree(degree: number): number {
    return degreeImportance(degree, this.degreeMax);
  }

  /** "Node fade" opacity for a node at the current zoom (scale): importance lifted by "Zoom reveal".
   *  1 when the effect is off. */
  private nodeAlpha(n: FgNode, scale: number): number {
    // A selected node (its ego network) or a search match overrides the fade → always solid, so
    // what you're inspecting and everything it touches stays fully visible. (See edgeAlpha too.)
    if (this.fadeOverridden(this.nodeInFocus(n.id))) return 1;
    return nodeFadeAlpha(
      this.normDegree(n.__degree ?? 0),
      scale,
      this.nodeFadeStart,
      this.nodeFadeFull,
      this.nodeRevealLo,
      this.nodeRevealHi
    );
  }

  /** True when an active selection (ego set) or search match should ignore the importance fade and
   *  render solid. When nothing is selected/searched this is false → the fade applies normally. */
  private fadeOverridden(inFocus: boolean): boolean {
    return (this.search.searchActive || this.neighborFocus.active) && inFocus;
  }

  /** "Node fade" opacity for an EDGE (reuse path): importance = min of its two endpoints' importance,
   *  so an edge is never more visible than its faintest end (no lines to ghost nodes). Same fade band
   *  + zoom reveal as nodes. `linkColor` passes this.currentZoom; drawLink passes its own scale. */
  private edgeAlpha(l: FgLink, zoom: number): number {
    // Selected edge (+ its endpoints), the selected node's incident edges, or a search match → solid.
    if (this.fadeOverridden(this.edgeInFocus(l.id))) return 1;
    const a = this.fgNodeById.get(String(linkEndId(l.source)));
    const b = this.fgNodeById.get(String(linkEndId(l.target)));
    const imp = Math.min(this.normDegree(a?.__degree ?? 0), this.normDegree(b?.__degree ?? 0));
    return nodeFadeAlpha(imp, zoom, this.nodeFadeStart, this.nodeFadeFull, this.nodeRevealLo, this.nodeRevealHi);
  }

  private applyNodeVal(): void {
    this.fg?.nodeVal((n: FgNode) => this.nodeValFor(n));
  }

  /** Recompute every mirror node's collide bubble against the current sizing/hub params (no reheat —
   *  setNodeSizing is render-only; the new radii take effect on the next natural settle/relayout). */
  private recomputeCollideRadii(): void {
    for (const n of this.fgNodeById.values()) {
      const d = n.__degree ?? 0;
      n.__collideR = collideRadius(d, this.hubSeparation, this.hubSpacing, this.radiusForDegree(d), this.collideScale);
    }
    this.syncCollideRadii();
  }

  /** Re-push the per-node `__collideR` into the quadtree collide force. forceCollide reads its radii
   *  via `.radius(...)` only at initialize (not per tick), so after a radius recompute that does NOT
   *  reset graphData (the sizing / hub-separation sliders) we re-set the accessor to force a re-read.
   *  A graphData reset (setData) re-initializes the force on its own, so those paths don't need this. */
  private syncCollideRadii(): void {
    this.collideForce?.radius((n) => n.__collideR ?? 0);
  }

  /** Is this edge dimmed by the denoise filter (either endpoint low-connection)? Suppressed while a
   *  search or neighbor focus owns the emphasis. */
  private isDenoiseDimEdge(l: FgLink): boolean {
    // A non-dimming selection (mode 'none' = selectionFocusMode 'all') does NOT own the emphasis,
    // so denoise stays; only search or a dim/hide neighbor focus suppresses it.
    if (
      this.denoiseDimIds.size === 0 ||
      this.search.searchActive ||
      (this.neighborFocus.active && this.neighborFocus.mode !== 'none')
    )
      return false;
    return (
      this.denoiseDimIds.has(String(linkEndId(l.source))) ||
      this.denoiseDimIds.has(String(linkEndId(l.target)))
    );
  }

  /** Recompute the degree-radial target ring for every current mirror node using the live
   *  radialRing (called when the "Spread radius" slider changes). Mirrors setData's degree
   *  math but over the full existing mirror set, since no data delta is involved. */
  private retargetAllNodes(): void {
    const nodes = [...this.fgNodeById.values()];
    const links = [...this.fgLinkById.values()];
    const degree = new Map<string, number>();
    for (const l of links) {
      const a = linkEndId(l.source);
      const b = linkEndId(l.target);
      degree.set(a, (degree.get(a) ?? 0) + 1);
      degree.set(b, (degree.get(b) ?? 0) + 1);
    }
    this.setDegreeRange(degree); // keep degreeMax in sync on a retarget
    const maxDegree = this.degreeMax;
    const outerRing = this.radialRing * Math.max(1, Math.sqrt(nodes.length));
    for (const n of nodes) this.assignTarget(n, degree, maxDegree, outerRing);
    this.syncCollideRadii(); // assignTarget rewrote __collideR; re-push into the cached collide force
  }

  /** "Edge curvature" slider → re-fan the current MIRROR links (no reheat; curvature is a
   *  render property). Re-setting the accessor nudges force-graph to repaint. */
  setCurveAmount(amount: number): void {
    this.curveAmount = amount;
    const fg = this.fg;
    if (!fg) return;
    assignLinkCurvatures([...this.fgLinkById.values()], amount);
    fg.linkCurvature((l: FgLink) => l.__curvature ?? 0);
  }

  /** Update the search highlight state read by the draw callbacks, repaint so the rings /
   *  dim / hide treatment appears even while idle, and pan to frame the matched subset. */
  setSearch(state: SearchState): void {
    this.search = state;
    const fg = this.fg;
    if (!fg) return;
    this.keepRedrawing(200);
    // After matches resolve, frame just the matched subset (matched nodes + endpoints of
    // matched edges). Skip when there are no matches so a typo doesn't yank the camera to
    // an empty frame; yields to a hand-driven camera (markIntentionalReframe resets it).
    const focus = state.focusNodeIds;
    if (!focus || focus.size === 0 || this.userMovedCamera) return;
    // A structural relayout is in flight (e.g. selecting an episode after the render subset
    // had emptied — its nodes are freshly re-added with NO positions yet, clustered at the
    // origin). Fitting now would frame that origin cluster and strand the camera top-left
    // while the sim spreads the nodes off-screen ("hung, not movable"). Let onEngineStop's
    // settle-fit frame the focus subset once positions resolve — it already handles searchActive.
    if (this.fitPending) return;
    this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: FgNode) => focus.has(n.id)));
  }

  /** Neighbor focus for the selected node's ego network (renderer-only, no relayout). */
  setNeighborFocus(state: NeighborFocusState): void {
    this.neighborFocus = state;
    this.keepRedrawing(200);
  }

  /** The selected node/edge (detail panel open) — drawn with a blue ring/line that overrides the
   *  amber search highlight. Renderer-only repaint. */
  /** Transient hover-preview from the detail panel's Connections list: ring the hovered
   *  connection (and, for an edge, its two endpoints) WITHOUT selecting it. Renderer-only;
   *  cleared on mouse-leave via setPreview(null). */
  setPreview(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    this.preview = sel;
    this.previewNodeIds = new Set();
    if (sel?.kind === 'node') {
      this.previewNodeIds.add(sel.id);
    } else if (sel?.kind === 'edge') {
      const l = this.fgLinkById.get(sel.id);
      if (l) {
        this.previewNodeIds.add(String(linkEndId(l.source)));
        this.previewNodeIds.add(String(linkEndId(l.target)));
      }
    }
    this.keepRedrawing(150);
  }

  setSelection(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    this.selected = sel;
    this.keepRedrawing(120);
  }

  /** Resolve the effective focus for THIS draw — search wins, else neighbor focus. `off` means
   *  the node/edge is outside the focus set; `mode` says how to treat it ('dim'/'hide'/'none'). */
  private focusFor(inFocus: boolean): { off: boolean; mode: 'dim' | 'hide' | 'none' } {
    if (this.search.searchActive) {
      if (this.search.searchFocusMode === 'highlight') return { off: false, mode: 'none' };
      return { off: !inFocus, mode: this.search.searchFocusMode };
    }
    if (this.neighborFocus.active) return { off: !inFocus, mode: this.neighborFocus.mode };
    return { off: false, mode: 'none' };
  }

  /** Push the model's glow-timestamp map; drive frames while halos fade, then idle. */
  setRecent(recent: Record<string, number>): void {
    this.recent = recent;
    if (this.fg && Object.keys(recent).length > 0) this.keepRedrawing(GLOW_MS + 150);
  }

  /** Frame the whole graph (or the current search subset) — the toolbar "Fit to view". */
  fitToView(): void {
    const fg = this.fg;
    if (!fg) return;
    this.userMovedCamera = false;
    const focus = this.search.focusNodeIds;
    if (focus && focus.size > 0) {
      this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: FgNode) => focus.has(n.id)));
    } else {
      this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60));
    }
  }

  /** Slide the camera to centre the given nodes (keeping zoom) — backs the detail panel's
   *  "click a connection → bring it into view". Pans to their centroid; no-op until they're
   *  positioned. A panel-driven recentre is intentional, so it clears the user-moved flag. */
  centerOn(nodeIds: string[]): void {
    const fg = this.fg;
    if (!fg) return;
    const pts = nodeIds
      .map((id) => this.fgNodeById.get(id))
      .filter((n): n is FgNode => !!n && n.x != null && n.y != null);
    if (pts.length === 0) return;
    const cx = pts.reduce((s, n) => s + (n.x ?? 0), 0) / pts.length;
    const cy = pts.reduce((s, n) => s + (n.y ?? 0), 0) / pts.length;
    this.userMovedCamera = false;
    this.programmaticFit(() => fg.centerAt?.(cx, cy, FIT_ANIM_MS));
  }

  /** Hand the camera back to auto-fit — call on intentional reframes (filter change, new
   *  search, manual reload) so a prior manual zoom doesn't suppress the post-change fit. */
  markIntentionalReframe(): void {
    this.userMovedCamera = false;
  }

  /** Re-run the force layout on the CURRENT in-memory data (with the current filters) — full-energy
   *  reheat + zoom-to-fit, but NO server re-fetch (that's `reload`). Re-spreads the visible graph
   *  from its present positions. */
  relayout(): void {
    const fg = this.fg;
    if (!fg) return;
    this.retargetAllNodes(); // recompute each node's radial target for the current set
    fg.d3VelocityDecay?.(VELOCITY_DECAY_SPREAD);
    fg.d3AlphaDecay?.(ALPHA_DECAY_SPREAD);
    fg.cooldownTicks?.(COOLDOWN_TICKS_SPREAD);
    this.markIntentionalReframe(); // allow the post-settle auto-fit
    this.fitPending = true;
    fg.d3ReheatSimulation?.(); // alpha→1 restart → forces re-spread the current nodes
  }

  destroy(): void {
    if (this.programmaticZoomTimer) clearTimeout(this.programmaticZoomTimer);
    if (this.redrawTimer) clearTimeout(this.redrawTimer);
    this.themeObserver?.disconnect();
    const fg = this.fg;
    if (fg) {
      fg.pauseAnimation?.();
      fg._destructor?.();
      this.fg = null;
    }
  }

  // ── internals ──────────────────────────────────────────────────────────────────────────

  /** Reconcile the durable mirrors against the current render set. Existing mirrors keep
   *  object identity (→ their simulated x/y persist); display fields are refreshed. */
  private reconcile(
    rNodes: RenderNode[],
    rLinks: RenderLink[]
  ): { fgNodes: FgNode[]; fgLinks: FgLink[]; freshNodeIds: string[] } {
    const fgNodes: FgNode[] = [];
    const freshNodeIds: string[] = [];
    const nodeIds = new Set<string>();
    for (const n of rNodes) {
      nodeIds.add(n.id);
      let m = this.fgNodeById.get(n.id);
      if (!m) {
        m = { id: n.id, type: n.type, name: n.name };
        this.fgNodeById.set(n.id, m);
        freshNodeIds.push(n.id);
      } else {
        m.type = n.type; // refresh display fields; KEEP x/y/vx/vy/fx/fy/index/__targetR
        m.name = n.name;
      }
      fgNodes.push(m);
    }
    for (const id of [...this.fgNodeById.keys()]) if (!nodeIds.has(id)) this.fgNodeById.delete(id);

    const fgLinks: FgLink[] = [];
    const linkIds = new Set<string>();
    for (const l of rLinks) {
      linkIds.add(l.id);
      const invalid = !!(l.invalid_at || l.expired_at);
      let m = this.fgLinkById.get(l.id);
      if (!m) {
        // New mirror: endpoints as ids; force-graph resolves them to the mirror node objects.
        m = {
          id: l.id,
          source: linkEndId(l.source),
          target: linkEndId(l.target),
          rel_type: l.rel_type,
          invalid,
          aggregate: l.aggregate,
          collapsedIds: l.collapsedIds,
          whole: l.whole
        };
        this.fgLinkById.set(l.id, m);
      } else {
        m.rel_type = l.rel_type; // keep m.source/m.target (force-graph resolved them to nodes)
        m.invalid = invalid; // validity can flip on a provenance-merge pulse
        m.aggregate = l.aggregate; // an aggregate's collapsed set changes as the cap/filters change
        m.collapsedIds = l.collapsedIds;
        m.whole = l.whole; // "X relations" vs "N other relations" can flip as the cap changes
      }
      fgLinks.push(m);
    }
    for (const id of [...this.fgLinkById.keys()]) if (!linkIds.has(id)) this.fgLinkById.delete(id);

    return { fgNodes, fgLinks, freshNodeIds };
  }

  private assignTarget(
    n: FgNode,
    degree: Map<string, number>,
    maxDegree: number,
    outerRing: number
  ): void {
    const d = degree.get(n.id) ?? 0;
    n.__degree = d; // stash for the per-node charge/collide accessors (hub separation) + sizing
    // Collide bubble base = the node's DRAWN radius (degree-based sizing) + pad, so bigger nodes
    // always keep their spacing. radiusForDegree needs this.degreeMax, set by the caller before this loop.
    n.__collideR = collideRadius(d, this.hubSeparation, this.hubSpacing, this.radiusForDegree(d), this.collideScale);
    // Soften the hub target: at hubSep>0 the busiest nodes aim at a small inner BAND instead of
    // radius 0, so degreeRadial stops reeling every hub into the exact centre (which made them
    // look clumped). The band grows with "Hub spacing" (capped) so the radial pull doesn't fight
    // a large requested spread. innerBand is 0 at hubSep=0 → original "hubs to dead centre" behavior.
    const bandFraction = Math.min(HUB_BAND_FRACTION * this.hubSpacing, HUB_BAND_FRACTION_MAX);
    const innerBand = outerRing * bandFraction * this.hubSeparation;
    n.__targetR = innerBand + (1 - d / maxDegree) * (outerRing - innerBand);
  }

  /** Seed each freshly-arrived node near the centroid of its already-placed neighbours so
   *  it animates in next to where it connects instead of flying from the origin. */
  private seedNewNodePositions(
    newNodes: FgNode[],
    links: FgLink[],
    placed: Map<string, FgNode>
  ): void {
    if (newNodes.length === 0) return;
    const newIds = new Set(newNodes.map((n) => n.id));
    // newId -> running sum of neighbour coords + count.
    const acc = new Map<string, { x: number; y: number; n: number }>();
    for (const l of links) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      if (newIds.has(a) && !newIds.has(b)) this.addNeighbour(acc, placed, a, b);
      if (newIds.has(b) && !newIds.has(a)) this.addNeighbour(acc, placed, b, a);
    }
    for (const n of newNodes) {
      const e = acc.get(n.id);
      if (e && e.n > 0) {
        // Spread co-arriving siblings around the neighbour centroid (≈±35px) so they don't
        // stack on the same point; physics then separates them the rest of the way.
        const jitter = () => (Math.random() - 0.5) * 70;
        n.x = e.x / e.n + jitter();
        n.y = e.y / e.n + jitter();
      }
      // else: no placed neighbour (orphan / first batch) → let force-graph position it.
    }
  }

  private addNeighbour(
    acc: Map<string, { x: number; y: number; n: number }>,
    placed: Map<string, FgNode>,
    newId: string,
    otherId: string
  ): void {
    const other = placed.get(otherId);
    if (!other || other.x == null || other.y == null) return;
    const e = acc.get(newId) ?? { x: 0, y: 0, n: 0 };
    e.x += other.x;
    e.y += other.y;
    e.n += 1;
    acc.set(newId, e);
  }

  /** Run a programmatic camera fit while suppressing user-move detection for the duration
   *  of its animation (+ a small buffer past the last onZoom tick). */
  private programmaticFit(run: () => void): void {
    this.programmaticZoom = true;
    if (this.programmaticZoomTimer) clearTimeout(this.programmaticZoomTimer);
    run();
    this.programmaticZoomTimer = setTimeout(() => {
      this.programmaticZoom = false;
      this.programmaticZoomTimer = null;
    }, FIT_ANIM_MS + 150);
  }

  /** On settle, reframe ONLY the active-search matched subset (gated by fitPending + no user
   *  camera). Load / reload / filter relayouts intentionally do NOT auto zoom-to-fit the whole
   *  graph any more — the camera stays where it is; only "Fit to view" or a search reframes. */
  private onEngineStop(): void {
    const fg = this.fg;
    if (!fg || !this.fitPending) return;
    this.fitPending = false;
    if (this.userMovedCamera) return; // the user took the camera → don't snap it back
    if (this.search.searchActive) {
      const focus = this.search.focusNodeIds;
      if (focus && focus.size > 0) {
        this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60, (n: FgNode) => focus.has(n.id)));
      }
    }
  }

  private keepRedrawing(ms: number): void {
    const fg = this.fg;
    if (!fg) return;
    const until = Date.now() + ms;
    if (until <= this.redrawUntil) return; // a longer redraw window is already pending
    this.redrawUntil = until;
    fg.autoPauseRedraw(false);
    if (this.redrawTimer) clearTimeout(this.redrawTimer);
    this.redrawTimer = setTimeout(() => {
      this.redrawTimer = null;
      this.redrawUntil = 0;
      this.fg?.autoPauseRedraw(true); // let the canvas idle again
    }, ms);
  }

  // ── link accessors (read by force-graph each frame) ──
  // Is this node/edge inside the active focus set (search matches, else neighbor ego set)?
  private nodeInFocus(id: string): boolean {
    if (this.search.searchActive) return !!this.search.focusNodeIds?.has(id);
    if (this.neighborFocus.active) return this.neighborFocus.nodeIds.has(id);
    return true;
  }
  private edgeInFocus(id: string): boolean {
    if (this.search.searchActive) return this.search.matchedEdgeIds.has(id);
    if (this.neighborFocus.active) return this.neighborFocus.edgeIds.has(id);
    return true;
  }

  private linkColor(l: FgLink): string {
    const s = this.search;
    // Selected edge → solid blue, overriding search/invalid styling (drawLink skips the dash too).
    if (this.selected?.kind === 'edge' && this.selected.id === l.id) return this.scheme.selectRing;
    // Transient hover-preview edge (Connections list) → emphasised amber line (skip when invalid,
    // so we don't double-draw over drawLink's dashed-red invalid line).
    if (this.preview?.kind === 'edge' && this.preview.id === l.id && !l.invalid) return this.scheme.matchRing;
    if (s.searchActive && s.matchedEdgeIds.has(l.id)) return this.scheme.matchRing;
    // Invalid edges always hide the built-in solid line — drawLink draws their dashed red line
    // (and applies any dim/hide there), so we never double-draw a solid + dashed line.
    if (l.invalid) return 'rgba(0,0,0,0)';
    const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
    if (off && mode === 'hide') return 'rgba(0,0,0,0)'; // invisible non-focus
    // "Node fade" applied to edges: scale the line (and its arrow, which reuses this colour) by the
    // edge's importance/zoom opacity. min-of-endpoints so it never outshines its faintest end.
    const fade = this.edgeAlpha(l, this.currentZoom);
    if (off && mode === 'dim') return scaleColorAlpha(this.scheme.linkColorDim, fade);
    if (this.isDenoiseDimEdge(l)) return scaleColorAlpha(this.scheme.linkColorDim, fade); // low-connection edge faded
    return scaleColorAlpha(this.scheme.linkColor, fade);
  }

  private linkWidth(l: FgLink): number {
    const s = this.search;
    if (this.selected?.kind === 'edge' && this.selected.id === l.id) return 3; // selected edge
    if (this.preview?.kind === 'edge' && this.preview.id === l.id) return 2.5; // hover preview
    if (s.searchActive && s.matchedEdgeIds.has(l.id)) return 2.5;
    const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
    if (off && mode === 'hide') return 0;
    if (l.aggregate) return 2.2; // aggregate edge: one point thicker than a normal edge (req)
    return 1.2;
  }

  // ── node draw (mode 'replace'): glow halo → colored disc → white icon → name label ──
  private drawNode(node: FgNode, ctx: CanvasRenderingContext2D, scale: number): void {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    const radius = this.radiusForDegree(node.__degree ?? 0); // degree-based size (halo/ring/icon/label all follow)
    const s = this.scheme;
    const search = this.search;

    // Focus treatment (search matches, else the selected node's neighbor ego set): 'hide' skips
    // off-focus nodes, 'dim' fades them, 'none'/in-focus draws normally. Layout unchanged either way.
    const { off: offFocus, mode: focusMode } = this.focusFor(this.nodeInFocus(node.id));
    if (offFocus && focusMode === 'hide') return; // fully hidden (layout unchanged)
    // Denoise dim (low-connection): render-only, lowest priority — suppressed while a search or
    // neighbor focus is active (those own the emphasis). Faded less aggressively than a focus miss.
    const denoiseDim =
      !this.search.searchActive &&
      !(this.neighborFocus.active && this.neighborFocus.mode !== 'none') &&
      this.denoiseDimIds.has(node.id);
    const dimmed = (offFocus && focusMode === 'dim') || denoiseDim;
    // "Node fade" (level-of-detail): opacity = smoothstep(importance; fadeStart, fadeFull). At ~0 the
    // node is culled (skip drawing; paintNodePointerArea also drops its hit area → non-interactive).
    // globalAlpha covers the icon + label below too, so a ghost node's text fades away with it.
    const fade = this.nodeAlpha(node, scale);
    if (fade <= FADE_CULL_EPSILON) return; // transparent → gone (not drawn, not interactive)
    const drawAlpha = fade * (dimmed ? (denoiseDim ? 0.25 : 0.12) : 1);
    const fadeApplied = drawAlpha < 1;
    if (fadeApplied) {
      ctx.save();
      ctx.globalAlpha = drawAlpha; // restored at the end of this draw
    }

    // 1. Flash for fresh/updated nodes (fades over GLOW_MS): a soft filled halo plus a
    //    bright expanding ring so the "just added/updated" pop is clearly visible.
    const ts = this.recent[`n:${node.id}`];
    if (ts) {
      const age = Date.now() - ts;
      if (age <= GLOW_MS) {
        const alpha = 1 - age / GLOW_MS; // 1 → 0 over the glow window
        const grow = 1 - alpha; // 0 → 1 as it ages (ring expands outward)
        ctx.beginPath();
        ctx.arc(x, y, radius + 5 + 20 * grow, 0, 2 * Math.PI);
        ctx.fillStyle = `rgba(${s.glowFillRGB}, ${0.45 * alpha})`;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x, y, radius + 3 + 16 * grow, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(${s.glowRingRGB}, ${0.95 * alpha})`;
        ctx.lineWidth = 3 / scale; // ≈3px on-screen regardless of zoom
        ctx.stroke();
      }
    }

    // 2. Colored disc per type.
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = colorFor(node.type);
    ctx.fill();

    // 2b. Highlight ring: BLUE for the selected node (overrides search), else amber for a search
    //     match. Selection wins so a clicked node reads clearly even when it's also a match.
    const isSelectedNode = this.selected?.kind === 'node' && this.selected.id === node.id;
    if (isSelectedNode || (search.searchActive && search.matchedNodeIds.has(node.id))) {
      ctx.beginPath();
      ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = isSelectedNode ? s.selectRing : s.matchRing;
      ctx.lineWidth = (isSelectedNode ? 3 : 2.5) / scale; // selection ring a touch thicker
      ctx.stroke();
    }

    // 2c. Transient hover preview (Connections list): a DASHED ring (distinct from the solid
    //     selection/match ring) on the previewed node or a previewed edge's two endpoints.
    if (this.previewNodeIds.has(node.id)) {
      ctx.beginPath();
      ctx.arc(x, y, radius + 4.5, 0, 2 * Math.PI);
      ctx.setLineDash([4 / scale, 3 / scale]);
      ctx.strokeStyle = s.selectRing;
      ctx.lineWidth = 2 / scale;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 3. White Lucide icon inside.
    drawIcon(ctx, node.type, x, y, radius * 1.45, scale);

    // 4. Name label below the disc — wraps onto stacked lines; zoom-gated so a dense graph
    //    at low zoom isn't a mess of labels.
    const baseFont = labelFontSize(scale, this.nodeZoomMin, this.nodeZoomMax, this.nodeFontMin, this.nodeFontMax);
    if (baseFont !== null && node.name) {
      // Labels grow/shrink with the node's degree-based size, dampened (√ of the radius ratio) so a
      // big hub doesn't get a billboard. Reduces to baseFont when sizing is flat (radius == NODE_RADIUS).
      const fontSize = baseFont * Math.sqrt(radius / NODE_RADIUS);
      const lines = wrapLabel(node.name);
      const lineH = fontSize * 1.25;
      const top = y + radius + fontSize; // baseline of the first line
      lines.forEach((line, i) =>
        drawTextPill(ctx, line, x, top + i * lineH, fontSize, s.nodeText, s.pillBg)
      );
    }

    if (fadeApplied) ctx.restore(); // balance the globalAlpha save (focus dim × node fade)
  }

  /** force-graph hit-area painter (shadow canvas). Paint the disc in `color` so the click/hover area
   *  matches the drawn node — but paint NOTHING when "Node fade" has culled it, making it inert. */
  private paintNodePointerArea(
    node: FgNode,
    color: string,
    ctx: CanvasRenderingContext2D,
    scale: number
  ): void {
    if (this.nodeAlpha(node, scale) <= FADE_CULL_EPSILON) return; // transparent → non-interactive
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x ?? 0, node.y ?? 0, this.radiusForDegree(node.__degree ?? 0), 0, 2 * Math.PI);
    ctx.fill();
  }

  // ── link draw (mode 'after'): fresh-edge flash then the rotated relation label ──
  private drawLink(link: FgLink, ctx: CanvasRenderingContext2D, scale: number): void {
    // Edge flash for freshly added/updated edges — drawn FIRST (before the zoom-gated label)
    // so the "pop" is visible even when edge labels are hidden at low zoom.
    const ets = this.recent[`e:${link.id}`];
    if (ets) {
      const edgeAge = Date.now() - ets;
      if (edgeAge <= GLOW_MS) {
        const src = link.source;
        const tgt = link.target;
        if (
          src &&
          tgt &&
          typeof src === 'object' &&
          typeof tgt === 'object' &&
          src.x != null &&
          src.y != null &&
          tgt.x != null &&
          tgt.y != null
        ) {
          const a = 1 - edgeAge / GLOW_MS;
          const cps = link.__controlPoints as number[] | null;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(src.x, src.y);
          if (cps && cps.length === 2) {
            ctx.quadraticCurveTo(cps[0], cps[1], tgt.x, tgt.y);
          } else if (cps && cps.length === 4) {
            ctx.bezierCurveTo(cps[0], cps[1], cps[2], cps[3], tgt.x, tgt.y);
          } else {
            ctx.lineTo(tgt.x, tgt.y);
          }
          ctx.strokeStyle = `rgba(${this.scheme.glowRingRGB}, ${0.85 * a})`;
          ctx.lineWidth = (3.5 + 3 * (1 - a)) / scale; // thick, fades as it ages
          ctx.lineCap = 'round';
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    // Focus treatment for this edge (search wins, else neighbor focus). Hidden edges skip both
    // the dashed-invalid line below AND the label; dimmed ones fade.
    const { off: edgeOffFocus, mode: edgeFocusMode } = this.focusFor(this.edgeInFocus(link.id));
    const edgeHidden = edgeOffFocus && edgeFocusMode === 'hide';
    // Denoise-dimmed edges (an endpoint is low-connection) fade their label + invalid dash too.
    const edgeDim = (edgeOffFocus && edgeFocusMode === 'dim') || this.isDenoiseDimEdge(link);
    // "Node fade" applied to the edge label + dashed-invalid line (the solid line/arrow fade via
    // linkColor). min-of-endpoints opacity; ~0 → skip the label/dash entirely (line is already gone).
    const edgeFade = this.edgeAlpha(link, scale);
    if (edgeFade <= FADE_CULL_EPSILON) return;

    // Invalid (superseded) facts → dashed red line, drawn before the zoom-gated label so it shows
    // even when labels are hidden. Skipped when search-matched (keeps its amber highlight) or
    // focus-hidden. linkColor() already made the built-in solid line transparent for these.
    if (
      link.invalid &&
      !edgeHidden &&
      !(this.selected?.kind === 'edge' && this.selected.id === link.id) && // selected → solid blue
      !(this.search.searchActive && this.search.matchedEdgeIds.has(link.id))
    ) {
      const isrc = link.source;
      const itgt = link.target;
      if (
        isrc &&
        itgt &&
        typeof isrc === 'object' &&
        typeof itgt === 'object' &&
        isrc.x != null &&
        isrc.y != null &&
        itgt.x != null &&
        itgt.y != null
      ) {
        const cps = link.__controlPoints as number[] | null;
        ctx.save();
        ctx.globalAlpha = (edgeDim ? 0.2 : 1) * edgeFade;
        ctx.beginPath();
        ctx.moveTo(isrc.x, isrc.y);
        if (cps && cps.length === 2) ctx.quadraticCurveTo(cps[0], cps[1], itgt.x, itgt.y);
        else if (cps && cps.length === 4) ctx.bezierCurveTo(cps[0], cps[1], cps[2], cps[3], itgt.x, itgt.y);
        else ctx.lineTo(itgt.x, itgt.y);
        ctx.strokeStyle = this.scheme.edgeInvalid;
        ctx.lineWidth = 1.4 / scale;
        ctx.setLineDash([5 / scale, 4 / scale]);
        ctx.stroke();
        ctx.restore(); // restore clears the line dash for subsequent draws
      }
    }

    const fontSize = labelFontSize(scale, this.edgeZoomMin, this.edgeZoomMax, this.edgeFontMin, this.edgeFontMax);
    if (fontSize === null) return;
    if (edgeHidden) return; // non-focus edge label hidden
    const src = link.source;
    const tgt = link.target;
    if (!src || !tgt || typeof src !== 'object' || typeof tgt !== 'object') return;
    const sx = src.x;
    const sy = src.y;
    const tx = tgt.x;
    const ty = tgt.y;
    if (sx == null || sy == null || tx == null || ty == null) return;
    let text: string;
    if (link.aggregate) {
      // Aggregate label — "X relations" (whole pair) or "N other relations" (leftover). Never trimmed.
      text = aggregateLabel(link);
    } else {
      if (!link.rel_type) return;
      // Humanize (USES_NAME_IN_STORES → "Uses Name In Stores") + trim to the configured length.
      const human = humanizeRelType(link.rel_type);
      text = human.length > this.edgeLabelMax ? `${human.slice(0, this.edgeLabelMax - 1)}…` : human;
    }

    const s = this.scheme;
    // Label anchor = bezier point at t=0.5 (the visual middle of the arc).
    const cps = link.__controlPoints as number[] | null;
    let lx: number;
    let ly: number;
    let angle: number;
    if (cps && cps.length === 2) {
      // Quadratic arc (parallel edges): B(0.5) = ¼S + ½C + ¼E. Tangent at the midpoint is
      // parallel to S→E, so the straight-line angle still applies.
      lx = 0.25 * sx + 0.5 * cps[0] + 0.25 * tx;
      ly = 0.25 * sy + 0.5 * cps[1] + 0.25 * ty;
      angle = Math.atan2(ty - sy, tx - sx);
    } else if (cps && cps.length === 4) {
      // Cubic loop (self-edge): B(0.5) = ⅛S + ⅜C1 + ⅜C2 + ⅛E. Keep label upright.
      lx = 0.125 * sx + 0.375 * cps[0] + 0.375 * cps[2] + 0.125 * tx;
      ly = 0.125 * sy + 0.375 * cps[1] + 0.375 * cps[3] + 0.125 * ty;
      angle = 0;
    } else {
      // Straight line.
      lx = (sx + tx) / 2;
      ly = (sy + ty) / 2;
      angle = Math.atan2(ty - sy, tx - sx);
    }
    // Flip text so it's never upside-down (read left-to-right).
    if (angle > Math.PI / 2) angle -= Math.PI;
    if (angle < -Math.PI / 2) angle += Math.PI;

    ctx.save();
    ctx.globalAlpha = (edgeDim ? 0.15 : 1) * edgeFade; // label inherits the edge's fade (never brighter)
    ctx.translate(lx, ly);
    ctx.rotate(angle);
    // Rounded pill (same colour as the canvas bg) behind the label so it masks the line for
    // readability; radius scales with the font so it stays pill-shaped at every zoom.
    drawTextPill(ctx, text, 0, 0, fontSize, s.edgeText, s.edgePillBg, fontSize * 0.5);
    ctx.restore();
  }
}
