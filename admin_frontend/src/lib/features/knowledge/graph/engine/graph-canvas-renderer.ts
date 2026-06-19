import { colorFor, humanizeRelType } from '../knowledge-graph-style';
import {
  EDGE_FONT_MAX,
  EDGE_FONT_MIN,
  EDGE_ZOOM_MAX,
  EDGE_ZOOM_MIN,
  GLOW_MS,
  NODE_FONT_MAX,
  NODE_FONT_MIN,
  NODE_RADIUS,
  NODE_ZOOM_MAX,
  NODE_ZOOM_MIN
} from './graph-config';
import { drawIcon, drawTextPill, labelFontSize, wrapLabel } from './graph-draw';
import {
  NODE_FADE_FULL_DEFAULT,
  NODE_FADE_START_DEFAULT,
  NODE_REVEAL_HI_DEFAULT,
  NODE_REVEAL_LO_DEFAULT,
  degreeImportance,
  nodeFadeAlpha
} from './graph-forces';
import { computeScheme, type Scheme } from './graph-scheme';
import { linkEndId, type FgLink, type FgNode } from './graph-types';
import {
  FADE_CULL_EPSILON,
  aggregateLabel,
  scaleColorAlpha,
  type GraphSelection,
  type NeighborFocusState,
  type SearchState
} from './graph-engine-types';

/** Owns plain render state read by force-graph draw callbacks (no Svelte proxies). */
export class GraphCanvasRenderer {
  scheme: Scheme = computeScheme();
  recent: Record<string, number> = {};
  search: SearchState = {
    searchActive: false,
    matchedNodeIds: new Set(),
    matchedEdgeIds: new Set(),
    focusNodeIds: null,
    searchFocusMode: 'highlight'
  };
  neighborFocus: NeighborFocusState = {
    active: false,
    mode: 'dim',
    selectedId: '',
    nodeIds: new Set(),
    edgeIds: new Set()
  };
  selected: GraphSelection = null;
  preview: GraphSelection = null;
  previewNodeIds = new Set<string>();
  denoiseDimIds = new Set<string>();
  currentZoom = 1;

  edgeZoomMin = EDGE_ZOOM_MIN;
  edgeZoomMax = EDGE_ZOOM_MAX;
  edgeFontMin = EDGE_FONT_MIN;
  edgeFontMax = EDGE_FONT_MAX;
  nodeZoomMin = NODE_ZOOM_MIN;
  nodeZoomMax = NODE_ZOOM_MAX;
  nodeFontMin = NODE_FONT_MIN;
  nodeFontMax = NODE_FONT_MAX;
  edgeLabelMax = 22;
  nodeFadeStart = NODE_FADE_START_DEFAULT;
  nodeFadeFull = NODE_FADE_FULL_DEFAULT;
  nodeRevealLo = NODE_REVEAL_LO_DEFAULT;
  nodeRevealHi = NODE_REVEAL_HI_DEFAULT;
  nodeSizeMin = NODE_RADIUS;
  nodeSizeMax = NODE_RADIUS;
  degreeMax = 1;

  constructor(private readonly fgNodeById: Map<string, FgNode>) {}

  refreshScheme(): void {
    this.scheme = computeScheme();
  }

  setPreviewFromLink(sel: GraphSelection, fgLinkById: Map<string, FgLink>): void {
    this.preview = sel;
    this.previewNodeIds = new Set();
    if (sel?.kind === 'node') {
      this.previewNodeIds.add(sel.id);
    } else if (sel?.kind === 'edge') {
      const l = fgLinkById.get(sel.id);
      if (l) {
        this.previewNodeIds.add(String(linkEndId(l.source)));
        this.previewNodeIds.add(String(linkEndId(l.target)));
      }
    }
  }

  radiusForDegree(degree: number): number {
    if (this.nodeSizeMax <= this.nodeSizeMin) return this.nodeSizeMin;
    const t = this.degreeMax > 0 ? Math.sqrt(Math.max(0, degree)) / Math.sqrt(this.degreeMax) : 0;
    return this.nodeSizeMin + t * (this.nodeSizeMax - this.nodeSizeMin);
  }

  nodeValFor(n: FgNode): number {
    const ratio = this.radiusForDegree(n.__degree ?? 0) / NODE_RADIUS;
    return ratio * ratio;
  }

  setDegreeRange(degree: Map<string, number>): void {
    const vals = [...degree.values()];
    this.degreeMax = vals.length ? Math.max(1, ...vals) : 1;
  }

  private normDegree(degree: number): number {
    return degreeImportance(degree, this.degreeMax);
  }

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

  private fadeOverridden(inFocus: boolean): boolean {
    return (this.search.searchActive || this.neighborFocus.active) && inFocus;
  }

  private focusFor(inFocus: boolean): { off: boolean; mode: 'dim' | 'hide' | 'none' } {
    if (this.search.searchActive) {
      if (this.search.searchFocusMode === 'highlight') return { off: false, mode: 'none' };
      return { off: !inFocus, mode: this.search.searchFocusMode };
    }
    if (this.neighborFocus.active) return { off: !inFocus, mode: this.neighborFocus.mode };
    return { off: false, mode: 'none' };
  }

  private nodeAlpha(n: FgNode, scale: number): number {
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

  private edgeAlpha(l: FgLink, zoom: number): number {
    if (this.fadeOverridden(this.edgeInFocus(l.id))) return 1;
    const a = this.fgNodeById.get(String(linkEndId(l.source)));
    const b = this.fgNodeById.get(String(linkEndId(l.target)));
    const imp = Math.min(this.normDegree(a?.__degree ?? 0), this.normDegree(b?.__degree ?? 0));
    return nodeFadeAlpha(
      imp,
      zoom,
      this.nodeFadeStart,
      this.nodeFadeFull,
      this.nodeRevealLo,
      this.nodeRevealHi
    );
  }

  private isDenoiseDimEdge(l: FgLink): boolean {
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

  linkColor(l: FgLink): string {
    const s = this.search;
    if (this.selected?.kind === 'edge' && this.selected.id === l.id) return this.scheme.selectRing;
    if (this.preview?.kind === 'edge' && this.preview.id === l.id && !l.invalid)
      return this.scheme.matchRing;
    if (s.searchActive && s.matchedEdgeIds.has(l.id)) return this.scheme.matchRing;
    if (l.invalid) return 'rgba(0,0,0,0)';
    const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
    if (off && mode === 'hide') return 'rgba(0,0,0,0)';
    const fade = this.edgeAlpha(l, this.currentZoom);
    if (off && mode === 'dim') return scaleColorAlpha(this.scheme.linkColorDim, fade);
    if (this.isDenoiseDimEdge(l)) return scaleColorAlpha(this.scheme.linkColorDim, fade);
    return scaleColorAlpha(this.scheme.linkColor, fade);
  }

  linkWidth(l: FgLink): number {
    const s = this.search;
    if (this.selected?.kind === 'edge' && this.selected.id === l.id) return 3;
    if (this.preview?.kind === 'edge' && this.preview.id === l.id) return 2.5;
    if (s.searchActive && s.matchedEdgeIds.has(l.id)) return 2.5;
    const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
    if (off && mode === 'hide') return 0;
    if (l.aggregate) return 2.2;
    return 1.2;
  }

  /** Arrow length for force-graph's built-in directional arrow (0 when focus-hidden). */
  linkArrowLength(l: FgLink): number {
    const { off, mode } = this.focusFor(this.edgeInFocus(l.id));
    return off && mode === 'hide' ? 0 : 5;
  }

  drawNode(node: FgNode, ctx: CanvasRenderingContext2D, scale: number): void {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    const radius = this.radiusForDegree(node.__degree ?? 0);
    const s = this.scheme;
    const search = this.search;

    const { off: offFocus, mode: focusMode } = this.focusFor(this.nodeInFocus(node.id));
    if (offFocus && focusMode === 'hide') return;
    const denoiseDim =
      !this.search.searchActive &&
      !(this.neighborFocus.active && this.neighborFocus.mode !== 'none') &&
      this.denoiseDimIds.has(node.id);
    const dimmed = (offFocus && focusMode === 'dim') || denoiseDim;
    const fade = this.nodeAlpha(node, scale);
    if (fade <= FADE_CULL_EPSILON) return;
    const drawAlpha = fade * (dimmed ? (denoiseDim ? 0.25 : 0.12) : 1);
    const fadeApplied = drawAlpha < 1;
    if (fadeApplied) {
      ctx.save();
      ctx.globalAlpha = drawAlpha;
    }

    const ts = this.recent[`n:${node.id}`];
    if (ts) {
      const age = Date.now() - ts;
      if (age <= GLOW_MS) {
        const alpha = 1 - age / GLOW_MS;
        const grow = 1 - alpha;
        ctx.beginPath();
        ctx.arc(x, y, radius + 5 + 20 * grow, 0, 2 * Math.PI);
        ctx.fillStyle = `rgba(${s.glowFillRGB}, ${0.45 * alpha})`;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x, y, radius + 3 + 16 * grow, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(${s.glowRingRGB}, ${0.95 * alpha})`;
        ctx.lineWidth = 3 / scale;
        ctx.stroke();
      }
    }

    ctx.beginPath();
    ctx.arc(x, y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = colorFor(node.type);
    ctx.fill();

    const isSelectedNode = this.selected?.kind === 'node' && this.selected.id === node.id;
    if (isSelectedNode || (search.searchActive && search.matchedNodeIds.has(node.id))) {
      ctx.beginPath();
      ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = isSelectedNode ? s.selectRing : s.matchRing;
      ctx.lineWidth = (isSelectedNode ? 3 : 2.5) / scale;
      ctx.stroke();
    }

    if (this.previewNodeIds.has(node.id)) {
      ctx.beginPath();
      ctx.arc(x, y, radius + 4.5, 0, 2 * Math.PI);
      ctx.setLineDash([4 / scale, 3 / scale]);
      ctx.strokeStyle = s.selectRing;
      ctx.lineWidth = 2 / scale;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    drawIcon(ctx, node.type, x, y, radius * 1.45, scale);

    const baseFont = labelFontSize(
      scale,
      this.nodeZoomMin,
      this.nodeZoomMax,
      this.nodeFontMin,
      this.nodeFontMax
    );
    if (baseFont !== null && node.name) {
      const fontSize = baseFont * Math.sqrt(radius / NODE_RADIUS);
      const lines = wrapLabel(node.name);
      const lineH = fontSize * 1.25;
      const top = y + radius + fontSize;
      lines.forEach((line, i) =>
        drawTextPill(ctx, line, x, top + i * lineH, fontSize, s.nodeText, s.pillBg)
      );
    }

    if (fadeApplied) ctx.restore();
  }

  paintNodePointerArea(
    node: FgNode,
    color: string,
    ctx: CanvasRenderingContext2D,
    scale: number
  ): void {
    if (this.nodeAlpha(node, scale) <= FADE_CULL_EPSILON) return;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x ?? 0, node.y ?? 0, this.radiusForDegree(node.__degree ?? 0), 0, 2 * Math.PI);
    ctx.fill();
  }

  drawLink(link: FgLink, ctx: CanvasRenderingContext2D, scale: number): void {
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
          ctx.lineWidth = (3.5 + 3 * (1 - a)) / scale;
          ctx.lineCap = 'round';
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    const { off: edgeOffFocus, mode: edgeFocusMode } = this.focusFor(this.edgeInFocus(link.id));
    const edgeHidden = edgeOffFocus && edgeFocusMode === 'hide';
    const edgeDim = (edgeOffFocus && edgeFocusMode === 'dim') || this.isDenoiseDimEdge(link);
    const edgeFade = this.edgeAlpha(link, scale);
    if (edgeFade <= FADE_CULL_EPSILON) return;

    if (
      link.invalid &&
      !edgeHidden &&
      !(this.selected?.kind === 'edge' && this.selected.id === link.id) &&
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
        else if (cps && cps.length === 4)
          ctx.bezierCurveTo(cps[0], cps[1], cps[2], cps[3], itgt.x, itgt.y);
        else ctx.lineTo(itgt.x, itgt.y);
        ctx.strokeStyle = this.scheme.edgeInvalid;
        ctx.lineWidth = 1.4 / scale;
        ctx.setLineDash([5 / scale, 4 / scale]);
        ctx.stroke();
        ctx.restore();
      }
    }

    const fontSize = labelFontSize(
      scale,
      this.edgeZoomMin,
      this.edgeZoomMax,
      this.edgeFontMin,
      this.edgeFontMax
    );
    if (fontSize === null) return;
    if (edgeHidden) return;
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
      text = aggregateLabel(link);
    } else {
      if (!link.rel_type) return;
      const human = humanizeRelType(link.rel_type);
      text = human.length > this.edgeLabelMax ? `${human.slice(0, this.edgeLabelMax - 1)}…` : human;
    }

    const s = this.scheme;
    const cps = link.__controlPoints as number[] | null;
    let lx: number;
    let ly: number;
    let angle: number;
    if (cps && cps.length === 2) {
      lx = 0.25 * sx + 0.5 * cps[0] + 0.25 * tx;
      ly = 0.25 * sy + 0.5 * cps[1] + 0.25 * ty;
      angle = Math.atan2(ty - sy, tx - sx);
    } else if (cps && cps.length === 4) {
      lx = 0.125 * sx + 0.375 * cps[0] + 0.375 * cps[2] + 0.125 * tx;
      ly = 0.125 * sy + 0.375 * cps[1] + 0.375 * cps[3] + 0.125 * ty;
      angle = 0;
    } else {
      lx = (sx + tx) / 2;
      ly = (sy + ty) / 2;
      angle = Math.atan2(ty - sy, tx - sx);
    }
    if (angle > Math.PI / 2) angle -= Math.PI;
    if (angle < -Math.PI / 2) angle += Math.PI;

    ctx.save();
    ctx.globalAlpha = (edgeDim ? 0.15 : 1) * edgeFade;
    ctx.translate(lx, ly);
    ctx.rotate(angle);
    drawTextPill(ctx, text, 0, 0, fontSize, s.edgeText, s.edgePillBg, fontSize * 0.5);
    ctx.restore();
  }
}
