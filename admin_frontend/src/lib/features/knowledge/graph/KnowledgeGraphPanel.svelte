<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { Maximize2, Minimize2, RefreshCw, SlidersHorizontal } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { cn } from '$lib/utils';
  import type { KnowledgePageController } from '../state/knowledge-controller.svelte';
  import KnowledgeGraphFilterBar from './KnowledgeGraphFilterBar.svelte';
  import KnowledgeGraphOptionsPanel from './KnowledgeGraphOptionsPanel.svelte';
  import { colorFor } from './knowledge-graph-style';

  interface Props {
    ctl: KnowledgePageController;
  }
  let { ctl }: Props = $props();
  const graph = untrack(() => ctl.graph);

  // Node mount point for force-graph (it appends its own <canvas>).
  let container = $state<HTMLDivElement | null>(null);
  // 3rd-party canvas instance — loosely typed by design (no bundled d.ts shape
  // worth threading through for the MVP).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let fg: any = null;
  let disconnect: (() => void) | null = null;

  // Graph options panel (left overlay) + its live layout controls. The panel
  // edits these; $effects below push them into the force-graph instance.
  let optionsOpen = $state(false);
  let linkStrength = $state(0.5); // d3 link-force strength: 0 loose … 1 rigid
  let curveAmount = $state(0.45); // max bow for fanned parallel edges (0 = straight)

  // Expand: fills the content area below the sticky knowledge header/tabs.
  // Uses position:fixed so it escapes the page's padding/max-width wrapper;
  // z-[9] keeps it below the sticky knowledge header (z-10) and shell (z-20)
  // so the tabs stay reachable. `--admin-page-header-h` is published by
  // AdminPageHeader's ResizeObserver and is inherited even in fixed children.
  let expanded = $state(false);
  // Saved on expand, restored on collapse so the user returns to where they were.
  let scrollRestore = 0;

  function toggleExpand(): void {
    if (!expanded) {
      // Going into expanded mode.
      scrollRestore = typeof window === 'undefined' ? 0 : window.scrollY;
      expanded = true;
      // Wait for Svelte to render the scroll spacer (added in markup below
      // when expanded), then scroll past AdminPageHeader's pin threshold so
      // the knowledge header/tabs collapse to their compact sticky form —
      // that's the "go up to sticky mode" the user asked for. The spacer
      // keeps document height past the un-pin hysteresis so the header
      // STAYS pinned while the panel is position:fixed.
      requestAnimationFrame(() => {
        window.scrollTo(0, 600);
        // One more frame so the pin transition + AdminPageHeader's
        // ResizeObserver settle (smaller header → updated --admin-page-header-h
        // → our top calc recomputes) before measuring canvas dimensions.
        requestAnimationFrame(resize);
      });
    } else {
      // Collapsing: restore the scroll the user had before they expanded.
      expanded = false;
      requestAnimationFrame(() => {
        window.scrollTo(0, scrollRestore);
        requestAnimationFrame(resize);
      });
    }
  }

  // Node colour by ontology type lives in ./knowledge-graph-style so the filter
  // strip and this canvas renderer share one palette (colorFor imported above).

  // Node visual constants (graph-space units; canvas → screen via globalScale).
  const NODE_RADIUS = 10;
  const GLOW_MS = 3000;

  // ───────────────────────────────────────────────────────────────────────────
  // Label sizing — per-type "min/max font size mapped to min/max zoom".
  //
  // At zoom <= ZOOM_MIN the label is HIDDEN.
  // At zoom == ZOOM_MIN  the label renders at FONT_MIN px on-screen.
  // At zoom >= ZOOM_MAX  the label renders at FONT_MAX px on-screen (clamped).
  // In between: linear interpolation. Output is converted to canvas-space
  // units (divided by scale) by `labelFontSize` so the rendered pixel size
  // on the user's screen matches the configured FONT_MIN..FONT_MAX range.
  //
  // Tweak any of these and Vite HMR will reflect the change instantly.
  // ───────────────────────────────────────────────────────────────────────────
  const NODE_ZOOM_MIN = 1.0;   // below this zoom: node names hidden
  const NODE_ZOOM_MAX = 2.5;   // at and above: clamped to NODE_FONT_MAX
  const NODE_FONT_MIN = 8;     // on-screen px at NODE_ZOOM_MIN
  const NODE_FONT_MAX = 16;    // on-screen px at NODE_ZOOM_MAX

  const EDGE_ZOOM_MIN = 1.0;   // below this zoom: edge labels hidden
  const EDGE_ZOOM_MAX = 2.5;
  const EDGE_FONT_MIN = 8;
  const EDGE_FONT_MAX = 14;

  /**
   * Map the current zoom level to a canvas-space font size, or return null
   * when the label should be hidden. The returned value is already divided
   * by `scale` so passing it to ctx.font produces the configured on-screen
   * pixel size.
   */
  function labelFontSize(
    scale: number,
    zoomMin: number,
    zoomMax: number,
    fontMin: number,
    fontMax: number
  ): number | null {
    if (scale < zoomMin) return null;
    const onScreen =
      scale >= zoomMax
        ? fontMax
        : fontMin + ((scale - zoomMin) / (zoomMax - zoomMin)) * (fontMax - fontMin);
    return onScreen / scale;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Force-simulation knobs — tweak freely and Vite HMR will hot-reload.
  // These override force-graph's d3-force defaults to give the small personal-
  // KG corpus a less-clumped layout. The biggest perceptual lever is
  // CHARGE_STRENGTH (node-to-node repulsion); LINK_DISTANCE (edge resting
  // length) is the secondary lever.
  //
  // Rough scaling guide for THIS corpus shape (~50 nodes):
  //   tighter cluster:  LINK_DISTANCE 40,  CHARGE_STRENGTH -80,   CENTER 0.2
  //   balanced (now):   LINK_DISTANCE 80,  CHARGE_STRENGTH -240,  CENTER 0.05
  //   airy / spread:    LINK_DISTANCE 140, CHARGE_STRENGTH -500,  CENTER 0.03
  //   wide overview:    LINK_DISTANCE 200, CHARGE_STRENGTH -800,  CENTER 0.02
  // Negative CHARGE_STRENGTH = repulsion; less negative (or positive) = attract.
  // CENTER_STRENGTH < 1 loosens the pull-to-(0,0) so clusters can drift apart.
  // ───────────────────────────────────────────────────────────────────────────
  const LINK_DISTANCE = 80;
  const CHARGE_STRENGTH = -240;
  const CENTER_STRENGTH = 0.05;
  // Keeping orphaned / weakly-connected nodes from flying off:
  //  - GRAVITY pulls every node gently toward the origin (forceX/forceY-style).
  //    Links + charge dominate locally, so connected clusters keep their shape;
  //    the weak pull only matters for nodes with nothing else holding them.
  //  - CHARGE_DISTANCE_MAX caps how far node-node repulsion reaches, so a lone
  //    node isn't shoved across the canvas by the whole cluster's cumulative
  //    charge. Together they corral strays near the connected mass.
  const GRAVITY_STRENGTH = 0.03;
  const CHARGE_DISTANCE_MAX = 320;

  // A d3-force that pulls every node toward the origin (equivalent to
  // forceX(0)+forceY(0)) — written inline so we don't add a d3-force import just
  // for this. d3 calls force(alpha) each tick and force.initialize(nodes) on bind.
  function radialGravity(strength: number) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let simNodes: any[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const force: any = (alpha: number) => {
      for (const n of simNodes) {
        n.vx -= n.x * strength * alpha;
        n.vy -= n.y * strength * alpha;
      }
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    force.initialize = (nodes: any[]) => {
      simNodes = nodes;
    };
    return force;
  }

  // Dark-mode-aware color scheme — read once per canvas callback.
  // This app sets `data-theme="dark"` / `data-theme="light"` on <html>
  // (see shell-preferences.svelte.ts setTheme → `document.documentElement.dataset.theme`).
  // dataset.theme access is a single property read — essentially free per frame.
  type Scheme = {
    pillBg: string;      // node name pill background
    nodeText: string;    // node name pill text
    edgePillBg: string;  // edge label pill background
    edgeText: string;    // edge label pill text
    linkColor: string;   // edge line color
  };
  function getScheme(): Scheme {
    const dark = typeof document !== 'undefined' &&
      document.documentElement.dataset.theme === 'dark';
    return dark
      ? {
          pillBg:     'rgba(2,6,23,0.88)',
          nodeText:   'rgba(226,232,240,0.95)',
          edgePillBg: 'rgba(2,6,23,0.82)',
          edgeText:   'rgba(148,163,184,0.95)',
          linkColor:  'rgba(148,163,184,0.5)'
        }
      : {
          pillBg:     'rgba(255,255,255,0.88)',
          nodeText:   'rgba(15,23,42,0.92)',
          edgePillBg: 'rgba(255,255,255,0.82)',
          edgeText:   'rgba(71,85,105,0.95)',
          linkColor:  'rgba(148,163,184,0.45)'
        };
  }

  // Lucide icon path data — 24×24 viewBox, drawn in white inside each colored disc.
  // Hardcoded so the canvas render stays deterministic across platforms (emoji
  // glyph rendering varies). Path strings come straight from lucide@0.x svgs.
  type LucideIcon = {
    paths: string[];
    /** Optional circle parts as [cx, cy, r] in the 24×24 viewBox. */
    circles?: Array<[number, number, number]>;
  };
  const ICONS: Record<string, LucideIcon> = {
    Person: {
      paths: ['M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2'],
      circles: [[12, 7, 4]]
    },
    Place: {
      paths: ['M20 10c0 7-8 12-8 12s-8-5-8-12a8 8 0 0 1 16 0Z'],
      circles: [[12, 10, 3]]
    },
    Event: {
      paths: [
        'M8 2v4',
        'M16 2v4',
        'M3 10h18',
        'M3 4h18a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z'
      ]
    },
    Organization: {
      paths: [
        'M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z',
        'M10 6h4',
        'M10 10h4',
        'M10 14h4',
        'M10 18h4'
      ]
    },
    Object: {
      paths: [
        'M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z',
        'm3.3 7 8.7 5 8.7-5',
        'M12 22V12'
      ]
    },
    Entity: {
      paths: [],
      circles: [[12, 12, 8]]
    }
  };

  function resize(): void {
    if (fg && container) {
      fg.width(container.clientWidth).height(container.clientHeight);
    }
  }

  function drawIcon(
    ctx: CanvasRenderingContext2D,
    type: string,
    x: number,
    y: number,
    size: number,
    scale: number
  ): void {
    const icon = ICONS[type] ?? ICONS.Entity;
    const s = size / 24;
    ctx.save();
    ctx.translate(x - size / 2, y - size / 2);
    ctx.scale(s, s);
    ctx.strokeStyle = 'rgba(255,255,255,0.95)';
    // Compensate so stroke renders at ≈1.8px on-screen regardless of zoom.
    ctx.lineWidth = 1.8 / (s * scale);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const d of icon.paths) {
      ctx.stroke(new Path2D(d));
    }
    if (icon.circles) {
      for (const [cx, cy, r] of icon.circles) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, 2 * Math.PI);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function drawTextPill(
    ctx: CanvasRenderingContext2D,
    text: string,
    cx: number,
    cy: number,
    fontSize: number,
    textColor: string,
    bgColor: string
  ): void {
    ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const m = ctx.measureText(text);
    const padX = fontSize * 0.35;
    const padY = fontSize * 0.18;
    ctx.fillStyle = bgColor;
    ctx.fillRect(
      cx - m.width / 2 - padX,
      cy - fontSize / 2 - padY,
      m.width + 2 * padX,
      fontSize + 2 * padY
    );
    ctx.fillStyle = textColor;
    ctx.fillText(text, cx, cy);
  }

  // Replace force-graph's default node render so we stack: glow halo → colored
  // disc → white icon → name label below. 'replace' mode = we own the whole node.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function nodeCanvasObject(node: any, ctx: CanvasRenderingContext2D, scale: number): void {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    const radius = NODE_RADIUS;
    const s = getScheme();

    // 1. Glow halo for fresh nodes (fades over GLOW_MS).
    const ts = graph.recent()[`n:${node.id}`];
    if (ts) {
      const age = Date.now() - ts;
      if (age <= GLOW_MS) {
        const alpha = 1 - age / GLOW_MS;
        const haloR = radius + 14 * (1 - alpha);
        ctx.beginPath();
        ctx.arc(x, y, haloR, 0, 2 * Math.PI);
        ctx.fillStyle = `rgba(96, 165, 250, ${0.35 * alpha})`;
        ctx.fill();
      }
    }

    // 2. Colored disc per type.
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = colorFor(node.type);
    ctx.fill();

    // 3. White Lucide icon inside.
    drawIcon(ctx, node.type, x, y, radius * 1.45, scale);

    // 4. Name label below the disc — pill colors adapt to light/dark theme.
    // Skip when zoomed out — a dense graph at low zoom would just be a mess of labels.
    const fontSize = labelFontSize(
      scale,
      NODE_ZOOM_MIN,
      NODE_ZOOM_MAX,
      NODE_FONT_MIN,
      NODE_FONT_MAX
    );
    if (fontSize !== null && node.name) {
      const text = node.name.length > 28 ? node.name.slice(0, 27) + '…' : node.name;
      drawTextPill(ctx, text, x, y + radius + fontSize, fontSize, s.nodeText, s.pillBg);
    }
  }

  // Draw the relation name on each edge, rotated to follow the edge, kept upright.
  // 'after' mode = drawn on top of the default link line. For parallel edges
  // (and self-loops) the line is a bezier arc (see assignLinkCurvatures +
  // linkCurvature); we place the label at the arc apex so the labels separate
  // along with the lines. force-graph computes link.__controlPoints just before
  // this 'after' paint, so we read them directly.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function linkCanvasObject(link: any, ctx: CanvasRenderingContext2D, scale: number): void {
    const fontSize = labelFontSize(
      scale,
      EDGE_ZOOM_MIN,
      EDGE_ZOOM_MAX,
      EDGE_FONT_MIN,
      EDGE_FONT_MAX
    );
    if (fontSize === null) return;
    const src = link.source;
    const tgt = link.target;
    if (!src || !tgt || typeof src !== 'object' || typeof tgt !== 'object') return;
    const sx = src.x;
    const sy = src.y;
    const tx = tgt.x;
    const ty = tgt.y;
    if (sx == null || sy == null || tx == null || ty == null) return;
    const text = link.rel_type;
    if (!text) return;

    const s = getScheme();
    // Label anchor = bezier point at t=0.5 (the visual middle of the arc).
    const cps = link.__controlPoints as number[] | null;
    let lx: number;
    let ly: number;
    let angle: number;
    if (cps && cps.length === 2) {
      // Quadratic arc (parallel edges): B(0.5) = ¼S + ½C + ¼E. Tangent at the
      // midpoint is parallel to S→E, so the straight-line angle still applies.
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
    ctx.translate(lx, ly);
    ctx.rotate(angle);
    drawTextPill(ctx, text, 0, 0, fontSize, s.edgeText, s.edgePillBg);
    ctx.restore();
  }

  // ── Parallel-edge & self-loop curvature ──────────────────────────────────
  // When 2+ edges share the same node pair they'd overlap as one straight line.
  // We fan them into distinct arcs by assigning each a linkCurvature (read by
  // force-graph per frame from link.__curvature). Recomputed whenever the visible
  // link set OR the curvature slider changes. The outer bow is curveAmount (the
  // "Edge curvature" control); topology-only, so it lives outside the render loop.
  const SELF_LOOP_BASE = 0.4; // first self-loop curvature; extra loops step out
  const SELF_LOOP_STEP = 0.3;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const linkEndId = (end: any): string => (end && typeof end === 'object' ? end.id : end);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function assignLinkCurvatures(links: any[]): void {
    // Group by UNORDERED node pair so A→B and B→A fan together.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const groups = new Map<string, any[]>();
    for (const l of links) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      const key = a === b ? `self ${a}` : a < b ? `${a} ${b}` : `${b} ${a}`;
      const g = groups.get(key);
      if (g) g.push(l);
      else groups.set(key, [l]);
    }
    for (const [key, group] of groups) {
      if (key.startsWith('self ')) {
        // Self-loops: stack increasing loop sizes so multiples don't coincide.
        group.forEach((l, i) => (l.__curvature = SELF_LOOP_BASE + i * SELF_LOOP_STEP));
        continue;
      }
      if (group.length === 1) {
        group[0].__curvature = 0; // lone edge stays straight
        continue;
      }
      // Symmetric fan from −curveAmount…+curveAmount (one straight when odd
      // count); opposite-direction edges flip sign so reciprocals separate.
      const last = group.length - 1;
      const refSource = linkEndId(group[last].source);
      group[last].__curvature = curveAmount;
      const delta = (2 * curveAmount) / last;
      for (let i = 0; i < last; i++) {
        let c = -curveAmount + i * delta;
        if (linkEndId(group[i].source) !== refSource) c *= -1;
        group[i].__curvature = c;
      }
    }
  }

  onMount(async () => {
    const { default: ForceGraph } = await import('force-graph');
    if (!container) return;
    // force-graph v1.51 exports a class; we use the legacy factory form
    // `ForceGraph()(container)` which still works at runtime. The cast also
    // drops the fluent generics so chained canvas-object hooks type-check.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Ctor = ForceGraph as unknown as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    fg = (Ctor()(container) as any)
      .nodeId('id')
      // Tooltip on hover still useful for full type + name when the on-canvas
      // label is truncated.
      .nodeLabel((n: { name: string; type: string }) => `${n.name} · ${n.type}`)
      .nodeRelSize(NODE_RADIUS) // matches drawn radius → default hit-test region works
      // Link color is read from the scheme on every frame so it responds to
      // light/dark theme switches without needing to re-init.
      .linkColor(() => getScheme().linkColor)
      .linkWidth(1.2)
      // Parallel edges between the same pair fan into arcs (see
      // assignLinkCurvatures); force-graph reads the per-link value each frame.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .linkCurvature((l: any) => l.__curvature ?? 0)
      .linkDirectionalArrowLength(5)
      .linkDirectionalArrowRelPos(0.92) // pull arrowhead inside the target disc
      .autoPauseRedraw(false)
      .onNodeClick((n: { id: string }) => graph.selectNode(n.id))
      .onLinkClick((l: { id: string }) => graph.selectEdge(l.id))
      .onBackgroundClick(() => graph.clearSelection())
      .nodeCanvasObjectMode(() => 'replace')
      .nodeCanvasObject(nodeCanvasObject)
      .linkCanvasObjectMode(() => 'after')
      .linkCanvasObject(linkCanvasObject);

    // d3-force tuning — see LINK_DISTANCE / CHARGE_STRENGTH / CENTER_STRENGTH
    // at the top of this file. Optional-chain the force getters because some
    // forces are only created lazily (older force-graph versions); d3ReheatSimulation
    // kicks the cooled-down sim so the new params take effect on the existing graph.
    // strength = the "Link strength" slider (overrides d3's auto value so the
    // control has a predictable effect); the strength $effect keeps it live.
    fg.d3Force('link')?.distance(LINK_DISTANCE).strength(linkStrength);
    // distanceMax caps repulsion range so strays aren't pushed to infinity.
    fg.d3Force('charge')?.strength(CHARGE_STRENGTH).distanceMax(CHARGE_DISTANCE_MAX);
    fg.d3Force('center')?.strength(CENTER_STRENGTH);
    // Gravity toward origin corrals orphaned / weakly-linked nodes near the rest.
    fg.d3Force('gravity', radialGravity(GRAVITY_STRENGTH));
    fg.d3ReheatSimulation?.();

    resize();
    await graph.load();
    disconnect = graph.connectEvents();
  });

  // Recreate the graph from the visible subset whenever membership OR filters
  // change. Feeding force-graph only the visible nodes/edges makes it re-layout
  // them to fill the frame, instead of leaving gaps where hidden nodes were.
  // Tracks visibleNodes/visibleLinks, which depend on both the data and the
  // hidden-type sets.
  $effect(() => {
    const nodes = graph.visibleNodes(); // tracked
    const links = graph.visibleLinks(); // tracked
    if (fg) {
      assignLinkCurvatures(links); // fan out any parallel edges before painting
      fg.graphData({ nodes, links });
    }
  });

  // "Link strength" slider → d3 link-force strength. Reheat so the new stiffness
  // resolves on the existing layout.
  $effect(() => {
    const s = linkStrength; // tracked
    if (fg) {
      fg.d3Force('link')?.strength(s);
      fg.d3ReheatSimulation?.();
    }
  });

  // "Edge curvature" slider → re-fan the current edges (no reheat; curvature is a
  // render property recomputed from the live link set). Re-setting the accessor
  // nudges force-graph to repaint with the new control points.
  $effect(() => {
    const amount = curveAmount; // tracked
    void amount;
    if (fg) {
      assignLinkCurvatures(graph.visibleLinks());
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      fg.linkCurvature((l: any) => l.__curvature ?? 0);
    }
  });

  onDestroy(() => {
    disconnect?.();
    if (fg) {
      fg.pauseAnimation?.();
      fg._destructor?.();
      fg = null;
    }
  });

  const node = $derived(graph.selectedNode());
  const edge = $derived(graph.selectedEdge());
</script>

<svelte:window onresize={resize} />

<!--
  Expanded mode: position:fixed below the sticky knowledge tabs.
  - top = shell header (4rem/64px) + knowledge page header (--admin-page-header-h)
  - CSS custom props ARE inherited by fixed children, so the var() resolves.
  - z-[9] stays below sticky knowledge header (z-10) and shell (z-20).
  Normal mode: flex column filling the page flow (min-h-[32rem]).
-->
<!--
  Layout strategy — both modes pin to the viewport's real chrome:
    shell header = 4rem (64px), AdminShell `min-h-16 sticky top-0`
    knowledge page header height = var(--admin-page-header-h) published by
      AdminPageHeader's ResizeObserver (≈80px expanded, ≈55px when pinned).
    sidebar column width = var(--admin-sidebar-w) published by AdminShell
      (264 / 84 / 0 mobile). CSS custom props inherit through fixed descendants.

  Expanded: position:fixed, RIGHT of the sidebar (left = var) and BELOW the
    sticky knowledge header (top = 4rem + page-header-h). bottom-0 + right-0
    fill the rest. z-[9] sits below the knowledge header (z-10) and shell
    (z-20), so the tabs stay reachable. Toolbar uses the same frosted style
    as the shell sticky header; canvas fills edge-to-edge.

  Collapsed: in-flow card with the same height calc, so the panel actually
    fills the content area (default `h-full` resolved to 0 because the
    AdminPageHeader <section> grid parent has no enforced height).
-->
<!-- Scroll spacer (expanded mode only): pushes document height past the
     AdminPageHeader pin threshold (PINNED_ENTER_SCROLL_Y = 80) so that
     window.scrollTo(0, 600) in toggleExpand can actually move scrollY past
     80 → header pins to its compact form. Sized at 150vh (well past any
     viewport's chrome) so the math works even on tall screens. The element
     is invisible to assistive tech / pointer; it only takes vertical space. -->
{#if expanded}
  <div aria-hidden="true" class="pointer-events-none h-[150vh]"></div>
{/if}

<div
  class={cn(
    'flex flex-col',
    expanded
      ? 'fixed bottom-0 right-0 z-[9] overflow-hidden bg-background'
      : 'gap-3'
  )}
  style={expanded
    ? // Expanded: header is pinned (~50-60px). Fallback 56px matches that.
      'top: calc(4rem + var(--admin-page-header-h, 56px)); left: var(--admin-sidebar-w, 0px)'
    : // Default: header is in its expanded form (~150px). Fallback 150px
      // matches that so the panel never overflows the viewport (which was
      // causing the page scrollbar in the previous iteration). 6rem buffer
      // covers py-(4|6) top+bottom + AdminPageHeader's section gap-5.
      'min-height: calc(100vh - 4rem - var(--admin-page-header-h, 150px) - 6rem)'}
>
  <!-- Top control row: filter strip on the left, action buttons (reload /
       expand) on the right — same line. Node/edge counts and live status live
       inside the canvas now (bottom-left overlay), not here.
       Expanded → frosted bar with bottom border, like the shell header.
       Collapsed → inline row with no chrome. -->
  <div
    class={cn(
      'flex items-center justify-between gap-3',
      expanded && 'border-b bg-background/85 px-4 py-2 backdrop-blur'
    )}
  >
    <div class="min-w-0 flex-1">
      {#if graph.nodes().length > 0}
        <KnowledgeGraphFilterBar {graph} />
      {/if}
    </div>
    <div class="flex shrink-0 items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onclick={() => graph.load()}
        disabled={graph.loading()}
        title="Reload graph"
      >
        <RefreshCw size={14} class={graph.loading() ? 'animate-spin' : ''} aria-hidden="true" />
        Reload
      </Button>
      <Button
        variant="outline"
        size="icon"
        onclick={toggleExpand}
        aria-label={expanded ? 'Collapse graph to page' : 'Expand graph to fill content area'}
        title={expanded ? 'Collapse graph' : 'Expand graph'}
      >
        {#if expanded}
          <Minimize2 size={16} aria-hidden="true" />
        {:else}
          <Maximize2 size={16} aria-hidden="true" />
        {/if}
      </Button>
    </div>
  </div>

  <!-- Canvas surface. In expanded mode it fills the rest of the fixed wrapper
       edge-to-edge (no border — the toolbar bar's border-b already separates).
       In collapsed mode it's a bordered card matching the page's other cards. -->
  <div
    class={cn(
      'relative flex-1 overflow-hidden bg-background',
      !expanded && 'rounded-lg border'
    )}
  >
    <div bind:this={container} class="absolute inset-0"></div>

    <!-- Graph options: toggle button in the upper-left corner + the left panel. -->
    {#if graph.nodes().length > 0}
      <button
        type="button"
        onclick={() => (optionsOpen = !optionsOpen)}
        class={cn(
          'absolute left-2 top-2 z-10 rounded-md border bg-background/85 p-1.5 shadow-sm backdrop-blur transition-colors hover:bg-accent',
          optionsOpen ? 'text-foreground' : 'text-muted-foreground'
        )}
        aria-label={optionsOpen ? 'Hide graph options' : 'Show graph options'}
        aria-pressed={optionsOpen}
        title="Graph options"
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
      </button>
      {#if optionsOpen}
        <div class="absolute left-2 top-12 z-10">
          <KnowledgeGraphOptionsPanel
            bind:linkStrength
            bind:curveAmount
            onClose={() => (optionsOpen = false)}
          />
        </div>
      {/if}
    {/if}

    {#if graph.nodes().length === 0 && !graph.loading()}
      <div class="absolute inset-0 grid place-items-center p-6">
        <InlineEmptyState
          message="No graph yet — build it from the Add tab (enable “build entity graph”)."
          hint="New nodes and relations appear here live as the graph builds."
        />
      </div>
    {/if}

    <!-- Stats overlay (bottom-left, inside the graph view): node/edge counts +
         live/ingest status. Shows visible/total when a filter is active. Type
         legend lives in the filter strip above (color dots on node chips). -->
    {#if graph.nodes().length > 0}
      <div
        class="pointer-events-none absolute bottom-2 left-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur-sm"
      >
        {#if graph.hasActiveFilters()}
          <span
            >{graph.visibleNodeCount()}/{graph.nodes().length} nodes · {graph.visibleEdgeCount()}/{graph.links()
              .length} edges</span
          >
        {:else}
          <span>{graph.nodes().length} nodes · {graph.links().length} edges</span>
        {/if}
        {#if graph.live()}
          <span class="inline-flex items-center gap-1.5 text-emerald-500">
            <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> live
          </span>
        {/if}
        {#if graph.progress()}
          <span>ingesting chunk {graph.progress()?.chunk_index}/{graph.progress()?.chunk_total}…</span>
        {/if}
        {#if graph.truncated()}
          <span class="text-amber-500">showing a capped subset</span>
        {/if}
      </div>
    {/if}

    <!-- provenance / selection panel -->
    {#if node || edge}
      <aside
        class="absolute right-0 top-0 flex h-full w-72 flex-col gap-2 overflow-auto border-l bg-background/95 p-4 text-sm"
      >
        <div class="flex items-start justify-between gap-2">
          <h3 class="font-medium">{node ? 'Entity' : 'Relation'}</h3>
          <button
            type="button"
            onclick={() => graph.clearSelection()}
            class="rounded px-1.5 text-muted-foreground hover:bg-accent"
            aria-label="Close details">✕</button
          >
        </div>

        {#if node}
          <div class="text-base font-semibold">{node.name}</div>
          <div class="text-muted-foreground">{node.type}</div>
          {#if node.aliases.length}
            <div><span class="text-muted-foreground">aliases:</span> {node.aliases.join(', ')}</div>
          {/if}
          <dl class="mt-1 grid grid-cols-2 gap-1">
            <dt class="text-muted-foreground">chunks</dt>
            <dd>{node.chunk_ids.length}</dd>
            <dt class="text-muted-foreground">documents</dt>
            <dd>{node.document_ids.length}</dd>
          </dl>
          {#if node.chunk_ids.length}
            <div class="mt-1 break-all text-xs text-muted-foreground">
              {node.chunk_ids.join(', ')}
            </div>
          {/if}
        {:else if edge}
          <div class="text-base font-semibold">{edge.rel_type}</div>
          <div class="text-muted-foreground">
            {graph.nodeName(edge.source)} → {graph.nodeName(edge.target)}
          </div>
          {#if edge.fact}
            <div class="mt-1 italic">“{edge.fact}”</div>
          {/if}
          <dl class="mt-1 grid grid-cols-2 gap-1">
            <dt class="text-muted-foreground">chunks</dt>
            <dd>{edge.chunk_ids.length}</dd>
            <dt class="text-muted-foreground">documents</dt>
            <dd>{edge.document_ids.length}</dd>
          </dl>
          {#if edge.chunk_ids.length}
            <div class="mt-1 break-all text-xs text-muted-foreground">
              {edge.chunk_ids.join(', ')}
            </div>
          {/if}
        {/if}
      </aside>
    {/if}
  </div>
</div>
