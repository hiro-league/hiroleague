/**
 * GraphCanvasEngine — thin coordinator around force-graph for the knowledge graph view.
 * Drawing lives in graph-canvas-renderer.ts; camera in graph-camera.ts; reconcile in graph-reconcile.ts.
 */
import type ForceGraph from 'force-graph';
import { forceCollide } from 'd3-force-3d';
import { humanizeRelType } from '../knowledge-graph-style';
import { GraphCamera } from './graph-camera';
import { GraphCanvasRenderer } from './graph-canvas-renderer';
import {
  GLOW_MS,
  NODE_RADIUS
} from './graph-config';
import {
  ALPHA_DECAY_DELTA,
  ALPHA_DECAY_SPREAD,
  ALPHA_DECAY_TWEAK,
  CHARGE_DISTANCE_MAX,
  CHARGE_STRENGTH,
  COLLIDE_ITERATIONS,
  COLLIDE_SCALE_DEFAULT,
  COOLDOWN_TICKS_DELTA,
  COOLDOWN_TICKS_SPREAD,
  COOLDOWN_TICKS_TWEAK,
  GRAVITY_STRENGTH,
  HUB_COLLIDE_STRENGTH,
  RADIAL_STRENGTH,
  VELOCITY_DECAY_DELTA,
  VELOCITY_DECAY_SPREAD,
  VELOCITY_DECAY_TWEAK,
  collideRadius,
  degreeRadial,
  hubChargeStrength,
  hubDistanceMax
} from './graph-forces';
import { assignLinkCurvatures } from './graph-links';
import {
  aggregateLabel,
  type GraphCanvasCallbacks,
  type NeighborFocusState,
  type RenderLink,
  type RenderNode,
  type SearchState,
  type StructuralContext
} from './graph-engine-types';
import {
  assignNodeTarget,
  computeDegreeMap,
  computeOuterRing,
  reconcileMirrors,
  seedNewNodePositions,
  type ReconcileParams
} from './graph-reconcile';
import type { FgLink, FgNode } from './graph-types';

export type {
  GraphCanvasCallbacks,
  NeighborFocusState,
  RenderLink,
  RenderNode,
  SearchState,
  StructuralContext
} from './graph-engine-types';

type FgInstance = ForceGraph<FgNode, FgLink>;

export class GraphCanvasEngine {
  private readonly callbacks: GraphCanvasCallbacks;
  private container: HTMLDivElement | null = null;
  private fg: FgInstance | null = null;
  private collideForce: ReturnType<typeof forceCollide<FgNode>> | null = null;

  private readonly fgNodeById = new Map<string, FgNode>();
  private readonly fgLinkById = new Map<string, FgLink>();
  private readonly renderer: GraphCanvasRenderer;
  private readonly camera: GraphCamera;

  private prevLoadVersion = -1;
  private prevHiddenNodes: Set<string> | null = null;
  private prevHiddenEdges: Set<string> | null = null;
  private prevFilterToken: string | null = null;

  private curveAmount = 0.45;
  private centerStrength = 0.05;
  private radialRing = 90;
  private hubSeparation = 0;
  private hubSpacing = 1;
  private collideScale = COLLIDE_SCALE_DEFAULT;
  private chargeStrength = CHARGE_STRENGTH;

  private redrawUntil = 0;
  private redrawTimer: ReturnType<typeof setTimeout> | null = null;
  private themeObserver: MutationObserver | null = null;

  constructor(callbacks: GraphCanvasCallbacks) {
    this.callbacks = callbacks;
    this.renderer = new GraphCanvasRenderer(this.fgNodeById);
    this.camera = new GraphCamera(
      () => this.fg,
      () => this.renderer.search
    );
  }

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
    this.renderer.nodeSizeMin = initial.nodeSizeMin;
    this.renderer.nodeSizeMax = initial.nodeSizeMax;

    const { default: ForceGraphCtor } = await import('force-graph');
    const factory = ForceGraphCtor as unknown as () => (el: HTMLElement) => FgInstance;
    const fg = factory()(container)
      .nodeId('id')
      .nodeLabel((n: FgNode) => `${n.name} · ${n.type}`)
      .linkLabel((l: FgLink) => {
        if (l.aggregate) return aggregateLabel(l);
        const human = humanizeRelType(l.rel_type);
        return human.length > this.renderer.edgeLabelMax ? human : '';
      })
      .nodeRelSize(NODE_RADIUS)
      .nodeVal((n: FgNode) => this.renderer.nodeValFor(n))
      .linkColor((l: FgLink) => this.renderer.linkColor(l))
      .linkWidth((l: FgLink) => this.renderer.linkWidth(l))
      .linkHoverPrecision(8)
      .linkCurvature((l: FgLink) => l.__curvature ?? 0)
      .linkDirectionalArrowLength((l: FgLink) => this.renderer.linkArrowLength(l))
      .linkDirectionalArrowRelPos(0.92)
      .autoPauseRedraw(true)
      .onNodeClick((n: FgNode) => this.callbacks.onNodeClick(n.id))
      .onLinkClick((l: FgLink) => this.callbacks.onLinkClick(l.id))
      .onBackgroundClick(() => this.callbacks.onBackgroundClick())
      .nodeCanvasObjectMode(() => 'replace')
      .nodeCanvasObject((n: FgNode, ctx: CanvasRenderingContext2D, scale: number) =>
        this.renderer.drawNode(n, ctx, scale)
      )
      .nodePointerAreaPaint((n: FgNode, color: string, ctx: CanvasRenderingContext2D, scale: number) =>
        this.renderer.paintNodePointerArea(n, color, ctx, scale)
      )
      .linkCanvasObjectMode(() => 'after')
      .linkCanvasObject((l: FgLink, ctx: CanvasRenderingContext2D, scale: number) =>
        this.renderer.drawLink(l, ctx, scale)
      );
    this.fg = fg;

    fg.d3Force('link')?.distance(initial.linkDistance).strength(initial.linkStrength);
    fg.d3Force('charge')
      ?.strength((n: FgNode) =>
        hubChargeStrength(n.__degree ?? 0, this.chargeStrength, this.hubSeparation)
      )
      .distanceMax(hubDistanceMax(CHARGE_DISTANCE_MAX, this.hubSeparation, this.hubSpacing));
    fg.d3Force('center')?.strength(this.centerStrength);
    void GRAVITY_STRENGTH;
    fg.d3Force('gravity', degreeRadial(RADIAL_STRENGTH));
    this.collideForce = forceCollide<FgNode>()
      .radius((n) => n.__collideR ?? 0)
      .strength(HUB_COLLIDE_STRENGTH)
      .iterations(COLLIDE_ITERATIONS);
    fg.d3Force('collide', this.collideForce);
    fg.onEngineStop(() => this.camera.onEngineStop());
    fg.onZoom((t) => {
      this.camera.onUserZoom();
      this.renderer.currentZoom = t.k;
      this.callbacks.onZoomChange?.(t.k);
    });
    this.renderer.currentZoom = fg.zoom();
    this.callbacks.onZoomChange?.(fg.zoom());
    fg.d3ReheatSimulation?.();

    this.renderer.refreshScheme();
    if (typeof MutationObserver !== 'undefined') {
      this.themeObserver = new MutationObserver(() => {
        this.renderer.refreshScheme();
        this.keepRedrawing(150);
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

  setData(rNodes: RenderNode[], rLinks: RenderLink[], ctx: StructuralContext): void {
    const fg = this.fg;
    if (!fg) return;

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

    const { fgNodes, fgLinks, freshNodeIds } = reconcileMirrors(
      rNodes,
      rLinks,
      this.fgNodeById,
      this.fgLinkById
    );

    const degree = computeDegreeMap(fgLinks);
    this.renderer.setDegreeRange(degree);
    const maxDegree = this.renderer.degreeMax;
    const outerRing = computeOuterRing(this.radialRing, fgNodes.length);
    assignLinkCurvatures(fgLinks, this.curveAmount);
    const reconcileParams = this.reconcileParams();

    if (structural) {
      for (const n of fgNodes) assignNodeTarget(n, degree, maxDegree, outerRing, reconcileParams);
      fg.d3VelocityDecay?.(VELOCITY_DECAY_SPREAD);
      fg.d3AlphaDecay?.(ALPHA_DECAY_SPREAD);
      fg.cooldownTicks?.(COOLDOWN_TICKS_SPREAD);
      fg.graphData({ nodes: fgNodes, links: fgLinks });
      this.camera.fitPending = true;
      fg.d3ReheatSimulation?.();
      return;
    }

    const fresh = new Set(freshNodeIds);
    const placed = new Map<string, FgNode>();
    for (const n of fgNodes) {
      if (!fresh.has(n.id) && n.x != null && n.y != null) placed.set(n.id, n);
    }
    const newNodes = fgNodes.filter((n) => fresh.has(n.id));
    for (const n of newNodes) assignNodeTarget(n, degree, maxDegree, outerRing, reconcileParams);
    seedNewNodePositions(newNodes, fgLinks, placed);
    fg.d3VelocityDecay?.(VELOCITY_DECAY_DELTA);
    fg.d3AlphaDecay?.(ALPHA_DECAY_DELTA);
    fg.cooldownTicks?.(COOLDOWN_TICKS_DELTA);
    fg.graphData({ nodes: fgNodes, links: fgLinks });
    this.camera.fitPending = false;
    fg.d3ReheatSimulation?.();
  }

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
    this.collideScale = opts.collideScale;
    fg.d3Force('charge')
      ?.strength((n: FgNode) =>
        hubChargeStrength(n.__degree ?? 0, this.chargeStrength, this.hubSeparation)
      )
      .distanceMax(hubDistanceMax(CHARGE_DISTANCE_MAX, this.hubSeparation, this.hubSpacing));
    if (opts.radialRing !== this.radialRing || hubChanged) {
      this.radialRing = opts.radialRing;
      this.retargetAllNodes();
    } else if (collideScaleChanged) {
      this.recomputeCollideRadii();
    }
    fg.d3VelocityDecay?.(VELOCITY_DECAY_TWEAK);
    fg.d3AlphaDecay?.(ALPHA_DECAY_TWEAK);
    fg.cooldownTicks?.(COOLDOWN_TICKS_TWEAK);
    fg.d3ReheatSimulation?.();
  }

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
    Object.assign(this.renderer, opts);
    this.keepRedrawing(120);
  }

  setNodeFade(opts: {
    nodeFadeStart: number;
    nodeFadeFull: number;
    nodeRevealLo: number;
    nodeRevealHi: number;
  }): void {
    Object.assign(this.renderer, opts);
    this.keepRedrawing(120);
  }

  setNodeSizing(opts: { minSize: number; maxSize: number }): void {
    this.renderer.nodeSizeMin = opts.minSize;
    this.renderer.nodeSizeMax = opts.maxSize;
    if (!this.fg) return;
    this.fg.nodeVal((n: FgNode) => this.renderer.nodeValFor(n));
    this.recomputeCollideRadii();
    this.keepRedrawing(150);
  }

  setDenoiseDim(ids: Set<string>): void {
    this.renderer.denoiseDimIds = ids;
    this.keepRedrawing(200);
  }

  setCurveAmount(amount: number): void {
    this.curveAmount = amount;
    const fg = this.fg;
    if (!fg) return;
    assignLinkCurvatures([...this.fgLinkById.values()], amount);
    fg.linkCurvature((l: FgLink) => l.__curvature ?? 0);
  }

  setSearch(state: SearchState): void {
    this.renderer.search = state;
    this.keepRedrawing(200);
    this.camera.maybeFrameSearchFocus();
  }

  setNeighborFocus(state: NeighborFocusState): void {
    this.renderer.neighborFocus = state;
    this.keepRedrawing(200);
  }

  setPreview(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    this.renderer.setPreviewFromLink(sel, this.fgLinkById);
    this.keepRedrawing(150);
  }

  setSelection(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    this.renderer.selected = sel;
    this.keepRedrawing(120);
  }

  setRecent(recent: Record<string, number>): void {
    this.renderer.recent = recent;
    if (this.fg && Object.keys(recent).length > 0) this.keepRedrawing(GLOW_MS + 150);
  }

  fitToView(): void {
    this.camera.fitToView();
  }

  centerOn(nodeIds: string[]): void {
    this.camera.centerOn(nodeIds, this.fgNodeById);
  }

  markIntentionalReframe(): void {
    this.camera.markIntentionalReframe();
  }

  relayout(): void {
    const fg = this.fg;
    if (!fg) return;
    this.retargetAllNodes();
    fg.d3VelocityDecay?.(VELOCITY_DECAY_SPREAD);
    fg.d3AlphaDecay?.(ALPHA_DECAY_SPREAD);
    fg.cooldownTicks?.(COOLDOWN_TICKS_SPREAD);
    this.camera.markIntentionalReframe();
    this.camera.fitPending = true;
    fg.d3ReheatSimulation?.();
  }

  destroy(): void {
    this.camera.destroy();
    if (this.redrawTimer) clearTimeout(this.redrawTimer);
    this.themeObserver?.disconnect();
    const fg = this.fg;
    if (fg) {
      fg.pauseAnimation?.();
      fg._destructor?.();
      this.fg = null;
    }
  }

  private reconcileParams(): ReconcileParams {
    return {
      hubSeparation: this.hubSeparation,
      hubSpacing: this.hubSpacing,
      collideScale: this.collideScale,
      radiusForDegree: (d) => this.renderer.radiusForDegree(d)
    };
  }

  private recomputeCollideRadii(): void {
    const params = this.reconcileParams();
    for (const n of this.fgNodeById.values()) {
      const d = n.__degree ?? 0;
      n.__collideR = collideRadius(
        d,
        params.hubSeparation,
        params.hubSpacing,
        params.radiusForDegree(d),
        params.collideScale
      );
    }
    this.syncCollideRadii();
  }

  private syncCollideRadii(): void {
    this.collideForce?.radius((n) => n.__collideR ?? 0);
  }

  private retargetAllNodes(): void {
    const nodes = [...this.fgNodeById.values()];
    const links = [...this.fgLinkById.values()];
    const degree = computeDegreeMap(links);
    this.renderer.setDegreeRange(degree);
    const maxDegree = this.renderer.degreeMax;
    const outerRing = computeOuterRing(this.radialRing, nodes.length);
    const params = this.reconcileParams();
    for (const n of nodes) assignNodeTarget(n, degree, maxDegree, outerRing, params);
    this.syncCollideRadii();
  }

  private keepRedrawing(ms: number): void {
    const fg = this.fg;
    if (!fg) return;
    const until = Date.now() + ms;
    if (until <= this.redrawUntil) return;
    this.redrawUntil = until;
    fg.autoPauseRedraw(false);
    if (this.redrawTimer) clearTimeout(this.redrawTimer);
    this.redrawTimer = setTimeout(() => {
      this.redrawTimer = null;
      this.redrawUntil = 0;
      this.fg?.autoPauseRedraw(true);
    }, ms);
  }
}
