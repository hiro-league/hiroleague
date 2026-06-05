<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import {
    Building2,
    CalendarDays,
    Circle,
    FileText,
    MapPin,
    Maximize2,
    Minimize2,
    Package,
    RefreshCw,
    Scan,
    Search,
    SlidersHorizontal,
    Spline,
    User,
    X
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { cn } from '$lib/utils';
  import {
    fetchGraphChunksDetail,
    searchGraphChunks,
    type GraphChunkDetail
  } from '$lib/api/knowledge';
  import type { KnowledgePageController } from '../state/knowledge-controller.svelte';
  import KnowledgeGraphFilterBar from './KnowledgeGraphFilterBar.svelte';
  import KnowledgeGraphOptionsPanel from './KnowledgeGraphOptionsPanel.svelte';
  import { colorFor } from './knowledge-graph-style';
  import {
    GRAPH_OPTION_DEFAULTS,
    MAX_LINKS_CAP,
    readGraphOptions,
    writeGraphOptions
  } from './knowledge-graph-prefs';

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
  // Set when the visible node/link set changes so the next engine-stop auto-fits the
  // view (see onEngineStop). Plain let — only read inside the force-graph callback.
  let fitPending = false;

  // ── force-graph mirror objects (CRITICAL — see reconcileFgData) ──────────────
  // force-graph / d3 store live simulation state (x, y, vx, vy, fx, fy, index) directly
  // on the node/link objects we hand them. Those objects MUST keep a stable identity and
  // persist across deltas. We CANNOT feed force-graph the model's Svelte $state objects:
  // every model rebuild (`nodes = [...nodeById.values()]`) makes Svelte create FRESH
  // proxies, and the $state set-trap stores writes in signals — never on the raw target —
  // so each fresh proxy reads x/y back as `undefined`, and d3 re-initialises every node to
  // a spiral position. That was the "the whole graph resets on every update" bug.
  // Instead we keep our own plain (non-reactive) mirror objects, reconciled by id from the
  // reactive model on each update: existing ids reuse their mirror (positions preserved),
  // new ids get a fresh mirror, removed ids are dropped.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgNodeById = new Map<string, any>();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgLinkById = new Map<string, any>();
  let prevLoadVersion = -1;
  let prevHiddenNodes: Set<string> | null = null;
  let prevHiddenEdges: Set<string> | null = null;

  // Reconcile the durable force-graph mirrors against the current reactive render set.
  // Returns the arrays to hand force-graph plus the ids of newly-created node mirrors
  // (so the delta path can seed/target only those). Existing mirrors keep their object
  // identity — and therefore their simulated positions — while display fields are refreshed.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function reconcileFgData(rNodes: any[], rLinks: any[]) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const fgNodes: any[] = [];
    const freshNodeIds: string[] = [];
    const nodeIds = new Set<string>();
    for (const n of rNodes) {
      nodeIds.add(n.id);
      let m = fgNodeById.get(n.id);
      if (!m) {
        m = { id: n.id, type: n.type, name: n.name };
        fgNodeById.set(n.id, m);
        freshNodeIds.push(n.id);
      } else {
        m.type = n.type; // refresh display fields; KEEP x/y/vx/vy/fx/fy/index/__targetR
        m.name = n.name;
      }
      fgNodes.push(m);
    }
    for (const id of [...fgNodeById.keys()]) if (!nodeIds.has(id)) fgNodeById.delete(id);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const fgLinks: any[] = [];
    const linkIds = new Set<string>();
    for (const l of rLinks) {
      linkIds.add(l.id);
      let m = fgLinkById.get(l.id);
      if (!m) {
        // New mirror: endpoints as ids; force-graph resolves them to the mirror node objects.
        m = { id: l.id, source: linkEndId(l.source), target: linkEndId(l.target), rel_type: l.rel_type };
        fgLinkById.set(l.id, m);
      } else {
        m.rel_type = l.rel_type; // keep m.source/m.target (force-graph resolved them to nodes)
      }
      fgLinks.push(m);
    }
    for (const id of [...fgLinkById.keys()]) if (!linkIds.has(id)) fgLinkById.delete(id);

    return { fgNodes, fgLinks, freshNodeIds };
  }

  // Seed each freshly-arrived node near the centroid of its already-placed neighbours
  // so it animates in next to where it connects instead of flying from the origin.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function seedNewNodePositions(newNodes: any[], links: any[], placed: Map<string, any>): void {
    if (newNodes.length === 0) return;
    const newIds = new Set(newNodes.map((n) => n.id));
    // newId -> running sum of neighbour coords + count.
    const acc = new Map<string, { x: number; y: number; n: number }>();
    const addNeighbour = (newId: string, otherId: string): void => {
      const other = placed.get(otherId);
      if (!other || other.x == null || other.y == null) return;
      const e = acc.get(newId) ?? { x: 0, y: 0, n: 0 };
      e.x += other.x;
      e.y += other.y;
      e.n += 1;
      acc.set(newId, e);
    };
    for (const l of links) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      if (newIds.has(a) && !newIds.has(b)) addNeighbour(a, b);
      if (newIds.has(b) && !newIds.has(a)) addNeighbour(b, a);
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

  // ── Camera ownership ────────────────────────────────────────────────────────
  // Auto zoom-to-fit otherwise fights the user: while physics are still settling
  // (initial load, live deltas) onEngineStop kept re-firing zoomToFit and snapping
  // the camera back, so a manual pan/zoom never "stuck" until the sim stopped.
  // Once the user moves the camera by hand we set this flag and STOP auto-fitting,
  // so their viewport holds. It's reset on intentional reframes (filter change,
  // a new search, the Fit button, manual Reload) where re-framing is expected.
  let userMovedCamera = false;
  // True only while one of OUR programmatic fits is animating, so the onZoom
  // handler doesn't mistake an automatic fit for a user gesture. Starts true so
  // force-graph's initial auto-centring isn't counted as a user move.
  let programmaticZoom = true;
  let programmaticZoomTimer: ReturnType<typeof setTimeout> | null = null;
  const FIT_ANIM_MS = 450; // zoomToFit camera-animation duration

  // Run a programmatic camera fit while suppressing user-move detection for the
  // duration of its animation (+ a small buffer past the last onZoom tick).
  function programmaticFit(run: () => void): void {
    programmaticZoom = true;
    if (programmaticZoomTimer) clearTimeout(programmaticZoomTimer);
    run();
    programmaticZoomTimer = setTimeout(() => {
      programmaticZoom = false;
      programmaticZoomTimer = null;
    }, FIT_ANIM_MS + 150);
  }

  // Frame the whole graph (or the current search subset) on demand — the toolbar
  // "Fit to view" button. Clears userMovedCamera so this counts as an intentional
  // reframe rather than being suppressed by it.
  function fitToView(): void {
    if (!fg) return;
    userMovedCamera = false;
    const focus = focusNodeIds;
    if (focus && focus.size > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: any) => focus.has(n.id)));
    } else {
      programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60));
    }
  }

  // Graph options panel (left overlay) + its live layout controls. The panel
  // edits these; $effects below push them into the force-graph instance.
  let optionsOpen = $state(false);
  // Graph-options sliders, seeded from localStorage so a tuned layout survives
  // reloads/navigation (persisted by the $effect below; see knowledge-graph-prefs).
  // MAX_LINKS_CAP doubles as the maxLinksPerPair slider max AND the "show all" value.
  const savedOptions = readGraphOptions();
  let linkStrength = $state(savedOptions.linkStrength); // d3 link-force strength: 0 loose … 1 rigid
  let linkDistance = $state(savedOptions.linkDistance); // d3 link-force resting length in px
  let curveAmount = $state(savedOptions.curveAmount); // max bow for fanned parallel edges (0 = straight)
  let maxLinksPerPair = $state(savedOptions.maxLinksPerPair); // parallel edges per pair; MAX = all
  // Search highlight treatment of non-matches: 'highlight' (ring only) | 'dim' | 'hide'.
  let searchFocusMode = $state(savedOptions.searchFocusMode);

  // Fullscreen: the expand button lifts the panel to a true full-viewport
  // overlay (position:fixed inset-0, above the shell) so the graph gets the
  // whole screen. Esc — or the minimize button — returns to the default
  // in-flow layout. The default (non-fullscreen) view already fills the
  // content area below the knowledge header, which is forced compact for the
  // Graph tab (KnowledgePage passes forceCompact) so the canvas has room.
  let fullscreen = $state(false);

  function toggleFullscreen(): void {
    fullscreen = !fullscreen;
    // Two frames so the layout swap settles before we re-measure the canvas.
    requestAnimationFrame(() => requestAnimationFrame(resize));
  }

  // Esc exits fullscreen (the standard "return from full screen" gesture).
  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape' && fullscreen) {
      fullscreen = false;
      requestAnimationFrame(() => requestAnimationFrame(resize));
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
  // LINK_DISTANCE is now the live `linkDistance` control (default 80) declared at
  // the top with the other graph-options state; the guide above still applies.
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
  // Degree-based "centrality" layout: pull strength toward the per-node target ring,
  // and how far the outermost (least-connected) ring sits. See degreeRadial + the
  // graphData $effect (which assigns each node's __targetR from its connection count).
  const RADIAL_STRENGTH = 0.08;
  const RADIAL_RING = 90; // outer-ring spacing; scaled by √(node count) in the $effect

  // Simulation cooling, switched per update kind (see the graphData $effect). graphData
  // always restarts the sim at alpha=1 and there's no public way to start gentler, so we
  // control how much MOTION that energy produces via decay instead:
  //  - STRUCTURAL (initial load / reload / reconcile / filter): d3 defaults → full energy
  //    so charge can spread the whole graph out (no cramping).
  //  - DELTA (live node/edge add): heavy velocity damping + fast alpha decay so the
  //    established layout only drifts slightly while the new nodes settle in locally,
  //    instead of re-solving into a whole new arrangement (the "whole graph jumps").
  const VELOCITY_DECAY_DEFAULT = 0.4; // d3 default
  const ALPHA_DECAY_DEFAULT = 0.0228; // d3 default (~300 ticks to cool)
  const VELOCITY_DECAY_DELTA = 0.8; // only 20% of velocity carries → small, gentle steps
  const ALPHA_DECAY_DELTA = 0.08; // cools in ~70 ticks → brief, local settle

  // A d3-force implementing the "most-connected in the middle, others around it"
  // layout the user asked for: each node is pulled toward a ring whose radius encodes
  // its connectivity (``n.__targetR``, assigned per-node in the graphData $effect from
  // its degree) — hubs target the centre, leaf/orphan nodes target the outer ring, so
  // the graph self-organizes around its busiest nodes instead of drifting into a blob.
  // Written inline to avoid a d3-force import; d3 calls force(alpha) each tick and
  // force.initialize(nodes) on bind. Replaces the old origin-only gravity.
  function degreeRadial(strength: number) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let simNodes: any[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const force: any = (alpha: number) => {
      for (const n of simNodes) {
        const r = Math.hypot(n.x, n.y);
        if (r < 1e-6) continue; // sitting at the origin: let charge nudge it out first
        // <0 pulls the node inward toward its ring, >0 pushes it outward.
        const k = (((n.__targetR ?? 0) - r) / r) * strength * alpha;
        n.vx += n.x * k;
        n.vy += n.y * k;
      }
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    force.initialize = (nodes: any[]) => {
      simNodes = nodes;
    };
    return force;
  }

  // Dark-mode-aware color scheme.
  // This app sets `data-theme="dark"` / `data-theme="light"` on <html>
  // (see shell-preferences.svelte.ts setTheme → `document.documentElement.dataset.theme`).
  type Scheme = {
    pillBg: string;      // node name pill background
    nodeText: string;    // node name pill text
    edgeText: string;    // edge label text (drawn directly on the edge, no pill bg)
    linkColor: string;   // edge line color
    linkColorDim: string; // edge line color for non-matches in "dim" search-focus mode
    matchRing: string;   // search-highlight ring/stroke (amber, semi-transparent)
    // "Just added/updated" flash colors as "r,g,b" (alpha applied per-frame as the glow
    // fades). Tuned to pop against every node-type disc color in both themes.
    glowRingRGB: string; // bright ring stroke around fresh nodes + the fresh-edge overlay
    glowFillRGB: string; // soft filled halo behind fresh nodes
  };
  function computeScheme(): Scheme {
    const dark = typeof document !== 'undefined' &&
      document.documentElement.dataset.theme === 'dark';
    return dark
      ? {
          pillBg:     'rgba(2,6,23,0.72)',
          nodeText:   'rgba(226,232,240,0.95)',
          // Stronger edge text (lighter + opaque) since it sits on the line with no
          // pill; lines themselves are more transparent so labels stay readable.
          edgeText:   'rgba(226,232,240,1)',
          linkColor:  'rgba(148,163,184,0.28)',
          linkColorDim: 'rgba(148,163,184,0.07)', // dimmed non-matches
          matchRing:  'rgba(251,191,36,0.6)', // amber-400, semi-transparent — pops but soft on dark
          glowRingRGB: '110,231,183', // emerald-300 — bright on dark
          glowFillRGB: '52,211,153'   // emerald-400
        }
      : {
          pillBg:     'rgba(255,255,255,0.72)',
          nodeText:   'rgba(15,23,42,0.92)',
          edgeText:   'rgba(30,41,59,1)',
          linkColor:  'rgba(148,163,184,0.25)',
          linkColorDim: 'rgba(148,163,184,0.08)', // dimmed non-matches
          matchRing:  'rgba(217,119,6,0.7)', // amber-600, semi-transparent — readable on light
          glowRingRGB: '5,150,105', // emerald-600 — saturated, reads on white
          glowFillRGB: '16,185,129' // emerald-500
        };
  }
  // PERF: getScheme() used to run inside every node AND edge draw callback, so it
  // read the DOM (dataset.theme) and allocated a fresh object thousands of times
  // per second at 60fps. The scheme only changes on theme toggle, so cache it here
  // and refresh via the MutationObserver wired up in onMount.
  let scheme: Scheme = computeScheme();

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

  // PERF: `new Path2D(d)` parses the SVG path mini-language on construction, which
  // is wasteful to redo for every icon path on every frame. Build each type's
  // Path2D[] once (lazily — Path2D is browser-only and this component also runs
  // during SSR) and reuse the cached objects in drawIcon.
  const iconPath2DCache = new Map<string, Path2D[]>();
  function iconPaths(type: string): Path2D[] {
    let cached = iconPath2DCache.get(type);
    if (!cached) {
      const icon = ICONS[type] ?? ICONS.Entity;
      cached = icon.paths.map((d) => new Path2D(d));
      iconPath2DCache.set(type, cached);
    }
    return cached;
  }

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
    // Reuse cached Path2D objects instead of re-parsing the path strings per frame.
    for (const p of iconPaths(type)) {
      ctx.stroke(p);
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

  // Draw a centered text label. When bgColor is null the text is drawn directly
  // (no pill background) — edge labels use this; node labels still pass a pill bg.
  function drawTextPill(
    ctx: CanvasRenderingContext2D,
    text: string,
    cx: number,
    cy: number,
    fontSize: number,
    textColor: string,
    bgColor: string | null
  ): void {
    ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if (bgColor) {
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
    }
    ctx.fillStyle = textColor;
    ctx.fillText(text, cx, cy);
  }

  // Wrap a node name onto multiple lines when it exceeds NODE_LABEL_WRAP chars.
  // Word-aware, with a hard break for single words longer than the limit; capped
  // at NODE_LABEL_MAX_LINES with an ellipsis on the last line if it overflows.
  const NODE_LABEL_WRAP = 12;
  const NODE_LABEL_MAX_LINES = 3;
  function wrapLabel(name: string): string[] {
    if (name.length <= NODE_LABEL_WRAP) return [name];
    const lines: string[] = [];
    let cur = '';
    const flush = () => {
      if (cur) lines.push(cur);
      cur = '';
    };
    for (const word of name.split(/\s+/)) {
      if (word.length > NODE_LABEL_WRAP) {
        flush();
        let rest = word;
        while (rest.length > NODE_LABEL_WRAP) {
          lines.push(rest.slice(0, NODE_LABEL_WRAP));
          rest = rest.slice(NODE_LABEL_WRAP);
        }
        cur = rest;
      } else if (!cur) {
        cur = word;
      } else if (`${cur} ${word}`.length <= NODE_LABEL_WRAP) {
        cur = `${cur} ${word}`;
      } else {
        flush();
        cur = word;
      }
    }
    flush();
    if (lines.length > NODE_LABEL_MAX_LINES) {
      const kept = lines.slice(0, NODE_LABEL_MAX_LINES);
      const last = kept[NODE_LABEL_MAX_LINES - 1];
      kept[NODE_LABEL_MAX_LINES - 1] = `${last.slice(0, NODE_LABEL_WRAP - 1)}…`;
      return kept;
    }
    return lines;
  }

  // Replace force-graph's default node render so we stack: glow halo → colored
  // disc → white icon → name label below. 'replace' mode = we own the whole node.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function nodeCanvasObject(node: any, ctx: CanvasRenderingContext2D, scale: number): void {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    const radius = NODE_RADIUS;
    const s = scheme; // cached; refreshed only on theme toggle (see onMount observer)

    // Search focus: a node is "off-focus" when a search is active and it's neither a match
    // nor an endpoint of a matched edge (focusNodeIds). 'hide' skips it entirely; 'dim'
    // fades it. 'highlight' (default) leaves non-matches fully drawn — ring only.
    const offFocus = searchActive && !focusNodeIds?.has(node.id);
    if (offFocus && searchFocusMode === 'hide') return; // fully hidden (layout unchanged)
    const dimmed = offFocus && searchFocusMode === 'dim';
    if (dimmed) {
      ctx.save();
      ctx.globalAlpha = 0.12; // faded non-match; restored at the end of this draw
    }

    // 1. Flash for fresh/updated nodes (fades over GLOW_MS): a soft filled halo plus a
    //    bright expanding ring so the "just added/updated" pop is clearly visible in both
    //    light and dark themes (colors come from the theme-aware scheme).
    const ts = graph.recent()[`n:${node.id}`];
    if (ts) {
      const age = Date.now() - ts;
      if (age <= GLOW_MS) {
        const alpha = 1 - age / GLOW_MS; // 1 → 0 over the glow window
        const grow = 1 - alpha; // 0 → 1 as it ages (ring expands outward)
        // Soft filled halo behind the disc.
        ctx.beginPath();
        ctx.arc(x, y, radius + 5 + 20 * grow, 0, 2 * Math.PI);
        ctx.fillStyle = `rgba(${s.glowFillRGB}, ${0.45 * alpha})`;
        ctx.fill();
        // Bright expanding ring — the part that actually "pops".
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

    // 2b. Search highlight: semi-transparent amber ring around matched nodes. Non-matches
    // are dimmed/hidden (or left as-is) per searchFocusMode above. Repaints are kicked by
    // the matchCount $effect so the ring appears/clears even while the canvas is idle.
    if (searchActive && matchedNodeIds.has(node.id)) {
      ctx.beginPath();
      ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = s.matchRing;
      ctx.lineWidth = 2.5 / scale; // ≈2.5px on-screen regardless of zoom
      ctx.stroke();
    }

    // 3. White Lucide icon inside.
    drawIcon(ctx, node.type, x, y, radius * 1.45, scale);

    // 4. Name label below the disc — pill colors adapt to light/dark theme. Names
    // longer than NODE_LABEL_WRAP chars wrap onto stacked lines (one pill each).
    // Skip when zoomed out — a dense graph at low zoom would just be a mess of labels.
    const fontSize = labelFontSize(
      scale,
      NODE_ZOOM_MIN,
      NODE_ZOOM_MAX,
      NODE_FONT_MIN,
      NODE_FONT_MAX
    );
    if (fontSize !== null && node.name) {
      const lines = wrapLabel(node.name);
      const lineH = fontSize * 1.25;
      const top = y + radius + fontSize; // baseline of the first line (unchanged)
      lines.forEach((line, i) =>
        drawTextPill(ctx, line, x, top + i * lineH, fontSize, s.nodeText, s.pillBg)
      );
    }

    if (dimmed) ctx.restore(); // balance the globalAlpha save from the focus block above
  }

  // Draw the relation name on each edge, rotated to follow the edge, kept upright.
  // 'after' mode = drawn on top of the default link line. For parallel edges
  // (and self-loops) the line is a bezier arc (see assignLinkCurvatures +
  // linkCurvature); we place the label at the arc apex so the labels separate
  // along with the lines. force-graph computes link.__controlPoints just before
  // this 'after' paint, so we read them directly.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function linkCanvasObject(link: any, ctx: CanvasRenderingContext2D, scale: number): void {
    // Edge flash for freshly added/updated edges — drawn FIRST (before the zoom-gated
    // label) so the "pop" is visible even when edge labels are hidden at low zoom. The
    // bright overlay follows the same straight/curved path the link line uses.
    const ets = graph.recent()[`e:${link.id}`];
    if (ets) {
      const edgeAge = Date.now() - ets;
      if (edgeAge <= GLOW_MS) {
        const src = link.source;
        const tgt = link.target;
        if (
          src && tgt && typeof src === 'object' && typeof tgt === 'object' &&
          src.x != null && src.y != null && tgt.x != null && tgt.y != null
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
          ctx.strokeStyle = `rgba(${scheme.glowRingRGB}, ${0.85 * a})`;
          ctx.lineWidth = (3.5 + 3 * (1 - a)) / scale; // thick, fades as it ages
          ctx.lineCap = 'round';
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    const fontSize = labelFontSize(
      scale,
      EDGE_ZOOM_MIN,
      EDGE_ZOOM_MAX,
      EDGE_FONT_MIN,
      EDGE_FONT_MAX
    );
    if (fontSize === null) return;
    // Search focus: a non-matching edge's label is hidden ('hide') or faded ('dim') to
    // match its line treatment; 'highlight' leaves it as-is.
    const edgeOffFocus = searchActive && !matchedEdgeIds.has(link.id);
    if (edgeOffFocus && searchFocusMode === 'hide') return;
    const edgeDim = edgeOffFocus && searchFocusMode === 'dim';
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

    const s = scheme; // cached; refreshed only on theme toggle (see onMount observer)
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
    if (edgeDim) ctx.globalAlpha = 0.15; // faded label for a dimmed non-match
    ctx.translate(lx, ly);
    ctx.rotate(angle);
    // null bg → edge label text drawn directly on the line (no background pill).
    drawTextPill(ctx, text, 0, 0, fontSize, s.edgeText, null);
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

  // Cap how many parallel edges are drawn between any node pair (and per self-
  // loop) so a densely-connected pair doesn't render as an unreadable fan. Keeps
  // the first `max` edges per group in visible-link order. max >= MAX_LINKS_CAP
  // means "show all" (no cap). The "Max links per pair" option drives this.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function capParallelLinks(links: any[], max: number): any[] {
    if (max >= MAX_LINKS_CAP) return links; // sentinel: unlimited
    const counts = new Map<string, number>();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const out: any[] = [];
    for (const l of links) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      //   delimiter can't collide with an id (same rationale as assignLinkCurvatures).
      const key = a === b ? `self ${a}` : a < b ? `${a} ${b}` : `${b} ${a}`;
      const n = counts.get(key) ?? 0;
      if (n >= max) continue; // pair already at the cap → drop this edge
      counts.set(key, n + 1);
      out.push(l);
    }
    return out;
  }

  // The capped link set fed to force-graph + curvature assignment. Recomputes when
  // the visible links change OR the "Max links per pair" control changes.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const displayLinks = $derived<any[]>(capParallelLinks(graph.visibleLinks(), maxLinksPerPair));

  // ── Search highlight aliases ────────────────────────────────────────────────
  // Local mirrors of the model's search state so the (non-reactive) force-graph
  // canvas callbacks can close over plain reactive values, and the redraw/zoom
  // $effects below can track them. Reading the model getters directly inside a
  // force-graph callback would work but wouldn't drive Svelte reactivity.
  const searchActive = $derived(graph.searchActive());
  const matchedNodeIds = $derived(graph.matchedNodeIds());
  const matchedEdgeIds = $derived(graph.matchedEdgeIds());

  // ── Redraw gating ─────────────────────────────────────────────────────────
  // PERF: force-graph's autoPauseRedraw (default true) lets the canvas go idle
  // once the simulation settles and there's no interaction. We previously forced
  // autoPauseRedraw(false), which repainted at 60fps FOREVER. Instead we keep
  // auto-pause on and only kick frames for our own animations (the glow-halo
  // fade) and one-off updates (theme switch), restoring idle after a deadline.
  let redrawUntil = 0;
  let redrawTimer: ReturnType<typeof setTimeout> | null = null;
  function keepRedrawing(ms: number): void {
    if (!fg) return;
    const until = Date.now() + ms;
    if (until <= redrawUntil) return; // a longer redraw window is already pending
    redrawUntil = until;
    fg.autoPauseRedraw(false);
    if (redrawTimer) clearTimeout(redrawTimer);
    redrawTimer = setTimeout(() => {
      redrawTimer = null;
      redrawUntil = 0;
      fg?.autoPauseRedraw(true); // let the canvas idle again
    }, ms);
  }

  // Observes <html data-theme> so a light/dark toggle refreshes the cached scheme.
  let themeObserver: MutationObserver | null = null;

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
      // light/dark theme switches without needing to re-init. A matched edge (search
      // highlight) is drawn in the amber match color and thicker; non-matches are
      // dimmed/hidden per searchFocusMode. Repaints kicked by the matchCount $effect.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .linkColor((l: any) => {
        if (!searchActive) return scheme.linkColor;
        if (matchedEdgeIds.has(l.id)) return scheme.matchRing;
        if (searchFocusMode === 'hide') return 'rgba(0,0,0,0)'; // invisible non-match
        if (searchFocusMode === 'dim') return scheme.linkColorDim;
        return scheme.linkColor;
      })
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .linkWidth((l: any) => {
        if (searchActive && matchedEdgeIds.has(l.id)) return 2.5;
        if (searchActive && searchFocusMode === 'hide' && !matchedEdgeIds.has(l.id)) return 0;
        return 1.2;
      })
      // Parallel edges between the same pair fan into arcs (see
      // assignLinkCurvatures); force-graph reads the per-link value each frame.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .linkCurvature((l: any) => l.__curvature ?? 0)
      // Hide arrowheads of non-matching edges in "hide" focus (color/width alone leaves
      // the arrow glyph visible). eslint-disable for the loosely-typed link param.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .linkDirectionalArrowLength((l: any) =>
        searchActive && searchFocusMode === 'hide' && !matchedEdgeIds.has(l.id) ? 0 : 5
      )
      .linkDirectionalArrowRelPos(0.92) // pull arrowhead inside the target disc
      .autoPauseRedraw(true) // PERF: idle when settled; we kick frames via keepRedrawing()
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
    fg.d3Force('link')?.distance(linkDistance).strength(linkStrength);
    // distanceMax caps repulsion range so strays aren't pushed to infinity.
    fg.d3Force('charge')?.strength(CHARGE_STRENGTH).distanceMax(CHARGE_DISTANCE_MAX);
    fg.d3Force('center')?.strength(CENTER_STRENGTH);
    // Degree-based radial centrality (hubs centre, leaves out) — replaces plain gravity.
    void GRAVITY_STRENGTH; // retained for the tuning guide above; radial uses RADIAL_STRENGTH
    fg.d3Force('gravity', degreeRadial(RADIAL_STRENGTH));
    // Auto zoom-to-fit once a relayout settles, but only when the visible set changed
    // (filters / cap / load) — so the user never has to pan-and-zoom after filtering.
    // Gated by fitPending so manual drags (which also cool the sim) don't snap the view.
    fg.onEngineStop(() => {
      if (!fitPending) return;
      fitPending = false;
      if (userMovedCamera) return; // the user took the camera → don't snap it back
      // During an active search the search-focus effect owns the frame (it fits the
      // matched subset). Fitting to ALL here would yank the camera off the matches
      // every time the sim cooled — the "search keeps resetting my zoom" bug.
      if (searchActive) {
        const focus = focusNodeIds;
        if (focus && focus.size > 0) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60, (n: any) => focus.has(n.id)));
        }
        return;
      }
      programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60));
    });
    // Detect a hand-driven pan/zoom so auto-fit yields to it (see userMovedCamera).
    // onZoom fires for our programmatic fits too, hence the programmaticZoom guard.
    fg.onZoom(() => {
      if (!programmaticZoom) userMovedCamera = true;
    });
    fg.d3ReheatSimulation?.();

    // Refresh the cached scheme + repaint once whenever the app toggles theme.
    // Replaces the old per-frame DOM read inside the draw callbacks.
    scheme = computeScheme();
    if (typeof MutationObserver !== 'undefined') {
      themeObserver = new MutationObserver(() => {
        scheme = computeScheme();
        keepRedrawing(150); // a few frames so new colors paint even while idle
      });
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
      });
    }

    resize();
    // Initial paint of the current graph. The LIVE SSE subscription is owned by the page
    // controller (knowledge-controller.svelte.ts), NOT here — so deltas emitted during a
    // build that started while this tab was closed are already in the model when we mount.
    await graph.load();
  });

  // Drive frames while glow halos fade in after fresh nodes/edges arrive, then
  // let the canvas idle. graph.recent() gains entries on each live upsert.
  $effect(() => {
    const r = graph.recent(); // tracked
    if (fg && Object.keys(r).length > 0) keepRedrawing(GLOW_MS + 150);
  });

  // Recreate the graph from the render subset whenever membership, filters, OR the
  // search-focus 'hide' subset change. Feeding force-graph only the rendered
  // nodes/edges makes it re-layout them to fill the frame, instead of leaving gaps
  // where hidden nodes were. renderNodes/renderLinks track visibleNodes/visibleLinks
  // (data + hidden-type sets) plus the 'hide' search-focus subset.
  $effect(() => {
    const nodes = renderNodes; // tracked
    const links = renderLinks; // tracked: capped visible links, minus 'hide'-mode non-matches
    const loadVersion = graph.loadVersion(); // tracked: structural reload signal
    const hidNodes = graph.hiddenNodeTypes(); // tracked: a filter change is structural
    const hidEdges = graph.hiddenEdgeTypes(); // tracked
    if (!fg) return;

    // Run the layout work OUTSIDE Svelte tracking (untrack): the only dependencies we want
    // are the tracked reads above (render set / filters / reload). force-graph mutates the
    // MIRROR objects (not these $state proxies), but we still untrack defensively so no
    // stray proxy read can turn a per-tick mutation into a graphData()+reheat loop (the old
    // "tense and shaky / never settles" bug).
    untrack(() => {
      // First paint = no mirrors yet (before this reconcile). Structural reloads / filter
      // changes also force a full relayout.
      const structural =
        loadVersion !== prevLoadVersion ||
        hidNodes !== prevHiddenNodes ||
        hidEdges !== prevHiddenEdges ||
        fgNodeById.size === 0; // first paint
      prevLoadVersion = loadVersion;
      prevHiddenNodes = hidNodes;
      prevHiddenEdges = hidEdges;

      // Reconcile the reactive render set into the durable force-graph mirrors. Existing
      // node mirrors keep their identity → their simulated x/y persist (THE fix for the
      // "graph resets every update" bug). `fresh` = mirrors created this pass.
      const { fgNodes, fgLinks, freshNodeIds } = reconcileFgData(nodes, links);

      // Degree-based radial targets for degreeRadial(): busiest node → centre (radius 0),
      // least-connected → outer ring, spacing scaled by √(node count). We gate only the
      // RING TARGETS on structural-vs-delta: recomputing them every delta makes outerRing
      // (∝ √N) grow each batch and yank the whole graph outward, so on a delta we leave
      // existing nodes' targets untouched and assign one only to the new arrivals.
      const degree = new Map<string, number>();
      for (const l of fgLinks) {
        const a = linkEndId(l.source);
        const b = linkEndId(l.target);
        degree.set(a, (degree.get(a) ?? 0) + 1);
        degree.set(b, (degree.get(b) ?? 0) + 1);
      }
      const maxDegree = Math.max(1, ...degree.values());
      const outerRing = RADIAL_RING * Math.max(1, Math.sqrt(fgNodes.length));
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const assignTarget = (n: any): void => {
        const d = degree.get(n.id) ?? 0;
        n.__targetR = (1 - d / maxDegree) * outerRing;
      };
      assignLinkCurvatures(fgLinks); // fan out any parallel edges before painting

      if (structural) {
        // Full relayout (reload / filter / first paint): retarget every node, full-energy
        // cooling so the whole graph spreads.
        for (const n of fgNodes) assignTarget(n);
        fg.d3VelocityDecay?.(VELOCITY_DECAY_DEFAULT);
        fg.d3AlphaDecay?.(ALPHA_DECAY_DEFAULT);
        fg.graphData({ nodes: fgNodes, links: fgLinks });
        fitPending = true;
        fg.d3ReheatSimulation?.();
        return;
      }

      // Incremental live delta: existing mirrors already hold their positions, so the layout
      // stays put. Seed each NEW node near its already-placed neighbours (warm start), target
      // only the new nodes, then a damped, fast-cooling reheat settles the new region locally
      // without the established graph jumping. No zoom-to-fit so the camera holds.
      const fresh = new Set(freshNodeIds);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const placed = new Map<string, any>();
      for (const n of fgNodes) {
        if (!fresh.has(n.id) && n.x != null && n.y != null) placed.set(n.id, n);
      }
      const newNodes = fgNodes.filter((n) => fresh.has(n.id));
      for (const n of newNodes) assignTarget(n);
      seedNewNodePositions(newNodes, fgLinks, placed);
      fg.d3VelocityDecay?.(VELOCITY_DECAY_DELTA);
      fg.d3AlphaDecay?.(ALPHA_DECAY_DELTA);
      fg.graphData({ nodes: fgNodes, links: fgLinks });
      fitPending = false; // don't snap the camera on live deltas
      fg.d3ReheatSimulation?.();
    });
  });

  // A filter change is an intentional reframe — hand the camera back to auto-fit
  // (the graphData effect above sets fitPending; onEngineStop then frames the new
  // set). Without this, a prior manual zoom would suppress the post-filter fit.
  // Runs once on mount too (sets the initial false — harmless).
  $effect(() => {
    graph.hiddenNodeTypes(); // tracked
    graph.hiddenEdgeTypes(); // tracked
    userMovedCamera = false;
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

  // "Link distance" slider → d3 link-force resting length. Reheat so edges relax
  // to the new length on the existing layout.
  $effect(() => {
    const d = linkDistance; // tracked
    if (fg) {
      fg.d3Force('link')?.distance(d);
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
      // Re-curve the force-graph MIRROR links (the objects actually being rendered), not the
      // reactive render set — __curvature lives on the mirrors handed to force-graph.
      assignLinkCurvatures([...fgLinkById.values()]);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      fg.linkCurvature((l: any) => l.__curvature ?? 0);
    }
  });

  // Persist the graph-options sliders to localStorage whenever any of them change
  // (also runs once on mount, writing the just-loaded values back — harmless).
  $effect(() => {
    writeGraphOptions({ linkStrength, linkDistance, curveAmount, maxLinksPerPair, searchFocusMode });
  });

  // "Reset" in the options panel → restore slider defaults (the $effect above then
  // re-persists them). Filters have their own "Clear filters" control.
  function resetGraphOptions(): void {
    linkStrength = GRAPH_OPTION_DEFAULTS.linkStrength;
    linkDistance = GRAPH_OPTION_DEFAULTS.linkDistance;
    curveAmount = GRAPH_OPTION_DEFAULTS.curveAmount;
    maxLinksPerPair = GRAPH_OPTION_DEFAULTS.maxLinksPerPair;
    searchFocusMode = GRAPH_OPTION_DEFAULTS.searchFocusMode;
  }

  // ── Unified search (node/edge text = instant client match; chunk text = backend) ──
  // The input drives graph.setSearchQuery (instant name/alias + rel_type/fact highlight);
  // the chunk-TEXT leg is a debounced backend call (point_ids → chunk matches mapped onto
  // nodes/edges by chunk_ids). Aborted/debounced so fast typing doesn't queue requests.
  const SEARCH_DEBOUNCE_MS = 250;
  let searchText = $state('');
  let searchBusy = $state(false);
  let searchAbort: AbortController | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleChunkSearch(term: string): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchAbort?.abort(); // a newer keystroke supersedes the in-flight lookup
    searchAbort = null;
    if (!term) {
      searchBusy = false;
      return;
    }
    searchBusy = true;
    searchTimer = setTimeout(() => {
      const ctrl = new AbortController();
      searchAbort = ctrl;
      // searchGraphChunks THROWS on error/abort — must catch or searchBusy sticks on.
      void (async () => {
        try {
          const res = await searchGraphChunks(term, ctrl.signal);
          if (ctrl.signal.aborted) return;
          graph.setMatchedChunkIds(res.data?.point_ids ?? []);
        } catch (err) {
          if (ctrl.signal.aborted) return; // expected on a newer keystroke / unmount
          console.error('graph chunk-text search failed', err);
          graph.setMatchedChunkIds([]); // fall back to client-only (name/rel) matches
        } finally {
          if (!ctrl.signal.aborted) searchBusy = false;
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
  }

  function onSearchInput(value: string): void {
    searchText = value;
    userMovedCamera = false; // a new query is an intentional reframe → re-enable focus fit
    graph.setSearchQuery(value); // instant client-side name/alias + rel_type/fact highlight
    scheduleChunkSearch(value.trim());
  }

  function clearSearch(): void {
    searchText = '';
    userMovedCamera = false; // clearing reframes (full set if 'hide' was relaying out)
    graph.setSearchQuery('');
    scheduleChunkSearch('');
  }

  // Node ids to frame on a search: matched nodes + the endpoints of matched edges, so an
  // edge-only hit still pans its pair into view. Null when no search is active.
  const focusNodeIds = $derived.by<Set<string> | null>(() => {
    if (!searchActive) return null;
    const ids = new Set<string>(matchedNodeIds);
    if (matchedEdgeIds.size > 0) {
      for (const l of displayLinks) {
        if (matchedEdgeIds.has(l.id)) {
          ids.add(String(linkEndId(l.source)));
          ids.add(String(linkEndId(l.target)));
        }
      }
    }
    return ids;
  });

  // ── Render subset (search-focus 'hide' relayout) ────────────────────────────
  // 'highlight'/'dim' keep every visible node in the sim and just ring/fade the
  // non-matches in the renderer. 'hide' instead REMOVES the off-focus nodes from
  // the data fed to force-graph, so the matched subset re-lays-out to fill the
  // frame (a true "recreate", matching how the type filters behave) rather than
  // leaving the hidden nodes frozen in place. Restores the full set the moment the
  // search clears or the mode switches away from 'hide'.
  const hideMode = $derived(searchActive && searchFocusMode === 'hide');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderNodes = $derived.by<any[]>(() => {
    const base = graph.visibleNodes();
    return hideMode && focusNodeIds ? base.filter((n) => focusNodeIds.has(n.id)) : base;
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderLinks = $derived.by<any[]>(() =>
    hideMode ? displayLinks.filter((l) => matchedEdgeIds.has(l.id)) : displayLinks
  );

  // Repaint when the match set changes so amber rings/edges appear (and clear) even while
  // the canvas is idle (autoPauseRedraw). Tracks the match sets via the aliases above.
  $effect(() => {
    void searchActive; // tracked
    void matchedNodeIds; // tracked
    void matchedEdgeIds; // tracked
    void searchFocusMode; // tracked — repaint when dim/hide/ring mode changes
    if (fg) keepRedrawing(200);
  });

  // After matches resolve, pan/zoom to frame just the matched subset (the "bring into
  // view" the user asked for). Skips when there are no matches so a typo doesn't yank the
  // camera to an empty frame; clearing the search leaves the view where it is. Yields to
  // a hand-driven camera (userMovedCamera) so a manual zoom after searching isn't undone;
  // onSearchInput resets that flag so each new query reframes.
  $effect(() => {
    const focus = focusNodeIds; // tracked
    if (!fg || !focus || focus.size === 0 || userMovedCamera) return;
    // force-graph zoomToFit(durationMs, padding, nodeFilter) — frame only matched nodes.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: any) => focus.has(n.id)));
  });

  onDestroy(() => {
    // NOTE: the graph SSE subscription is owned by the page controller, so we do NOT
    // tear it down here — leaving the Graph tab must not stop live deltas accumulating.
    chunkAbort?.abort(); // don't leave a chunk-detail request open after unmount
    searchAbort?.abort(); // ditto for an in-flight chunk-text search
    if (searchTimer) clearTimeout(searchTimer);
    if (programmaticZoomTimer) clearTimeout(programmaticZoomTimer);
    themeObserver?.disconnect();
    if (redrawTimer) clearTimeout(redrawTimer);
    if (fg) {
      fg.pauseAnimation?.();
      fg._destructor?.();
      fg = null;
    }
  });

  const node = $derived(graph.selectedNode());
  const edge = $derived(graph.selectedEdge());

  // ── Detail-panel provenance (lazy chunk-text lookup) ────────────────────────
  // The DTO only carries chunk_ids; when a node/edge is selected we fetch the real
  // chunk text + owning document titles so the panel can show content (and the
  // document name) instead of opaque ids. Grouped by document for display.
  // Map entity type → a Lucide icon (mirrors the canvas disc icons); relations use Spline.
  const NODE_TYPE_ICON: Record<string, typeof Circle> = {
    Person: User,
    Place: MapPin,
    Event: CalendarDays,
    Organization: Building2,
    Object: Package,
    Entity: Circle
  };
  const nodeIcon = (type: string): typeof Circle => NODE_TYPE_ICON[type] ?? Circle;

  const CHUNK_SNIPPET_CHARS = 220;
  let chunkDetails = $state<GraphChunkDetail[]>([]);
  let chunksLoading = $state(false);
  let expandedChunks = $state<Set<string>>(new Set());

  // Chunk event date (episode `valid_at`): the semantic "when this happened" time, not the
  // ingest time. Shown as an absolute date on each chunk card (full timestamp on hover).
  const chunkDateFmt = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
  function formatChunkDate(iso: string | null): { label: string; title: string } | null {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return { label: chunkDateFmt.format(d), title: d.toLocaleString() };
  }

  // chunk_ids of the current selection (node provenance is rolled up from its edges).
  const selectedChunkIds = $derived(node ? node.chunk_ids : edge ? edge.chunk_ids : []);
  const selectedDocCount = $derived(
    node ? node.document_ids.length : edge ? edge.document_ids.length : 0
  );

  function toggleChunk(id: string): void {
    const next = new Set(expandedChunks);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedChunks = next;
  }

  // Group fetched chunks by their document title for a "document → chunks" layout.
  const chunkGroups = $derived.by(() => {
    const groups = new Map<string, GraphChunkDetail[]>();
    for (const c of chunkDetails) {
      const title = c.document_title || c.document_id || 'Unknown document';
      const list = groups.get(title);
      if (list) list.push(c);
      else groups.set(title, [c]);
    }
    return [...groups.entries()].map(([title, chunks]) => ({ title, chunks }));
  });

  // In-flight chunk-detail request; aborted when the selection changes or the
  // panel unmounts so we never leak/queue same-origin connections (a leaked
  // request blocks the packaged admin UI — pages + API share one origin and the
  // browser caps ~6 connections per origin).
  let chunkAbort: AbortController | null = null;

  // Fetch chunk text whenever the selection (and thus its chunk_ids) changes.
  $effect(() => {
    const ids = selectedChunkIds; // tracked
    expandedChunks = new Set();
    chunkAbort?.abort(); // cancel a previous selection's still-pending lookup
    chunkAbort = null;
    if (ids.length === 0) {
      chunkDetails = [];
      chunksLoading = false;
      return;
    }
    const ctrl = new AbortController();
    chunkAbort = ctrl;
    chunkDetails = [];
    chunksLoading = true;
    // apiRequest THROWS on error/timeout/abort — must catch, or chunksLoading
    // sticks on "Loading…" forever and the rejection goes unhandled.
    void (async () => {
      try {
        const res = await fetchGraphChunksDetail(ids, ctrl.signal);
        if (ctrl.signal.aborted) return;
        chunkDetails = res.data?.chunks ?? [];
      } catch (err) {
        if (ctrl.signal.aborted) return; // expected on selection change / unmount
        console.error('graph chunk-detail lookup failed', err);
        chunkDetails = []; // panel falls back to "chunk text unavailable"
      } finally {
        if (!ctrl.signal.aborted) chunksLoading = false;
      }
    })();
    return () => ctrl.abort();
  });
</script>

<svelte:window onresize={resize} onkeydown={onKeydown} />

<!--
  Two layouts:

  Default (in-flow): a flex column that fills the content area below the
    knowledge header. The header is forced compact on the Graph tab
    (KnowledgePage → forceCompact), publishing a small --admin-page-header-h,
    so this min-height calc gives the canvas almost the whole viewport without
    any scroll trickery. The 3rem buffer is tuned to sit the panel just above
    <main>'s bottom padding — closing the old gap while staying short enough to
    never introduce a vertical scrollbar.

  Fullscreen (expand button): a true full-viewport overlay — position:fixed
    inset-0 above the shell (z-50). Covers the sidebar + header so the graph
    owns the whole screen. Esc or the minimize button returns to the default.
-->
<div
  class={cn(
    'flex flex-col',
    fullscreen ? 'fixed inset-0 z-50 overflow-hidden bg-background' : 'gap-3'
  )}
  style={fullscreen
    ? undefined
    : 'min-height: calc(100vh - 4rem - var(--admin-page-header-h, 150px) - 3rem)'}
>
  <!-- Top control row: filter strip on the left, action buttons (reload /
       expand) on the right — same line. Node/edge counts and live status live
       inside the canvas now (bottom-left overlay), not here.
       Fullscreen → frosted bar with bottom border, like the shell header.
       Default → inline row with no chrome. -->
  <div
    class={cn(
      'flex items-center justify-between gap-3',
      fullscreen && 'border-b bg-background/85 px-4 py-2 backdrop-blur'
    )}
  >
    <div class="min-w-0 flex-1">
      {#if graph.nodes().length > 0}
        <KnowledgeGraphFilterBar {graph} />
      {/if}
    </div>
    <div class="flex shrink-0 items-center gap-2">
      {#if graph.nodes().length > 0}
        <!-- Unified search: highlights matching nodes/edges (by name/alias, relation/fact,
             or chunk text) with an amber ring and frames them in view — never hides the
             rest. Theme-aware via the input's border/bg/ring tokens. -->
        <div class="relative">
          <Search
            size={14}
            class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            value={searchText}
            oninput={(e) => onSearchInput(e.currentTarget.value)}
            placeholder="Search graph…"
            aria-label="Search nodes, edges, and chunk text"
            class="h-8 w-44 rounded-md border bg-background pl-7 pr-16 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background sm:w-52 [&::-webkit-search-cancel-button]:hidden"
          />
          {#if searchActive}
            <div
              class="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1.5"
            >
              <span
                class="tabular-nums text-[10px] font-medium {graph.matchCount() > 0
                  ? 'text-amber-600 dark:text-amber-400'
                  : 'text-muted-foreground'}"
                title={`${graph.matchCount()} match${graph.matchCount() === 1 ? '' : 'es'}${searchBusy ? ' (searching chunks…)' : ''}`}
              >
                {searchBusy ? '…' : graph.matchCount()}
              </span>
              <button
                type="button"
                onclick={clearSearch}
                class="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="Clear search"
                title="Clear search"
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>
          {/if}
        </div>
      {/if}
      {#if graph.nodes().length > 0}
        <!-- Fit to view: reframe the whole graph (or the search subset) on demand,
             now that auto-fit yields to a hand-driven camera. -->
        <Button
          variant="outline"
          size="icon"
          onclick={fitToView}
          aria-label="Fit graph to view"
          title="Fit to view"
        >
          <Scan size={16} aria-hidden="true" />
        </Button>
      {/if}
      <Button
        variant="outline"
        size="sm"
        onclick={() => {
          userMovedCamera = false; // a manual reload should reframe the fresh data
          void graph.load();
        }}
        disabled={graph.loading()}
        title="Reload graph"
      >
        <RefreshCw size={14} class={graph.loading() ? 'animate-spin' : ''} aria-hidden="true" />
        Reload
      </Button>
      <Button
        variant="outline"
        size="icon"
        onclick={toggleFullscreen}
        aria-label={fullscreen ? 'Exit full screen (Esc)' : 'View graph full screen'}
        title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}
      >
        {#if fullscreen}
          <Minimize2 size={16} aria-hidden="true" />
        {:else}
          <Maximize2 size={16} aria-hidden="true" />
        {/if}
      </Button>
    </div>
  </div>

  <!-- Canvas surface. In fullscreen it fills the rest of the fixed wrapper
       edge-to-edge (no border — the toolbar bar's border-b already separates).
       In the default layout it's a bordered card matching the page's other cards. -->
  <div
    class={cn(
      'relative flex-1 overflow-hidden bg-background',
      !fullscreen && 'rounded-lg border'
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
            bind:linkDistance
            bind:curveAmount
            bind:maxLinksPerPair
            bind:searchFocusMode
            maxLinksCap={MAX_LINKS_CAP}
            onReset={resetGraphOptions}
            onClose={() => (optionsOpen = false)}
          />
        </div>
      {/if}
    {/if}

    {#if graph.nodes().length === 0 && !graph.loading()}
      <div class="absolute inset-0 grid place-items-center p-6">
        {#if graph.progress()}
          <InlineEmptyState
            message="Building knowledge graph…"
            hint={`Ingesting chunk ${graph.progress()?.chunk_index}/${graph.progress()?.chunk_total} — nodes and relations will appear here as they’re extracted.`}
          />
        {:else}
          <InlineEmptyState
            message="No graph yet — build it from the Add tab (enable “build entity graph”)."
            hint="New nodes and relations appear here live as the graph builds."
          />
        {/if}
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
      {@const isNode = !!node}
      {@const accent = node ? colorFor(node.type) : 'rgb(100,116,139)'}
      {@const HeaderIcon = node ? nodeIcon(node.type) : Spline}
      <aside
        class="absolute right-0 top-0 flex h-full w-80 flex-col overflow-hidden border-l bg-background/80 text-sm shadow-lg backdrop-blur"
      >
        <!-- header: entity/relation icon + type + name, tinted by type colour -->
        <div
          class="flex items-start gap-2.5 border-b p-3"
          style="background-color: color-mix(in srgb, {accent} 14%, transparent);"
        >
          <span
            class="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-md text-white"
            style="background-color: {accent};"
          >
            <HeaderIcon size={16} aria-hidden="true" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {isNode ? node?.type : 'Relation'}
            </div>
            <div class="truncate font-semibold" title={isNode ? node?.name : edge?.rel_type}>
              {isNode ? node?.name : edge?.rel_type}
            </div>
          </div>
          <button
            type="button"
            onclick={() => graph.clearSelection()}
            class="-mr-1 rounded px-1.5 text-muted-foreground hover:bg-accent"
            aria-label="Close details">✕</button
          >
        </div>

        <!-- body -->
        <div class="flex flex-1 flex-col gap-2 overflow-auto p-3">
          {#if node}
            {#if node.aliases.length}
              <div class="text-xs">
                <span class="text-muted-foreground">aliases:</span> {node.aliases.join(', ')}
              </div>
            {/if}
            <!-- #5: Graphiti's generated entity summary (already on the DTO). -->
            {#if node.summary}
              <div class="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                {node.summary}
              </div>
            {/if}
          {:else if edge}
            <div class="text-muted-foreground">
              {graph.nodeName(edge.source)} → {graph.nodeName(edge.target)}
            </div>
            {#if edge.fact}
              <div class="rounded-md bg-muted/40 p-2 text-xs italic">“{edge.fact}”</div>
            {/if}
          {/if}

          <!-- sources: real chunk text grouped by document (lazy-fetched on select) -->
          <div class="mt-1 flex items-center justify-between">
            <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
              >Sources</span
            >
            <span class="text-[11px] text-muted-foreground">
              {selectedChunkIds.length} chunk{selectedChunkIds.length === 1 ? '' : 's'} ·
              {selectedDocCount} doc{selectedDocCount === 1 ? '' : 's'}
            </span>
          </div>

          {#if selectedChunkIds.length === 0}
            <p class="text-xs text-muted-foreground">
              No source chunks — this entity has no edge-borne provenance (isolated node).
            </p>
          {:else if chunksLoading}
            <p class="text-xs text-muted-foreground">Loading chunk text…</p>
          {:else if chunkDetails.length === 0}
            <p class="text-xs text-muted-foreground">
              Chunk text unavailable (the source document may have been removed).
            </p>
          {:else}
            <div class="space-y-3">
              {#each chunkGroups as group (group.title)}
                <div>
                  <div class="mb-1 flex items-center gap-1.5 text-xs font-medium">
                    <FileText size={13} class="flex-none text-muted-foreground" aria-hidden="true" />
                    <span class="truncate" title={group.title}>{group.title}</span>
                  </div>
                  <div class="space-y-1.5">
                    {#each group.chunks as c (c.id)}
                      {@const expanded = expandedChunks.has(c.id)}
                      {@const long = c.text.length > CHUNK_SNIPPET_CHARS}
                      {@const date = formatChunkDate(c.valid_at)}
                      <div class="rounded-md border bg-muted/40 p-2 text-xs">
                        <!-- heading path (left, truncates) + event date (right, valid_at). -->
                        {#if c.heading_path || date}
                          <div
                            class="mb-0.5 flex items-center gap-2 text-[10px] text-muted-foreground"
                          >
                            <span class="min-w-0 flex-1 truncate" title={c.heading_path ?? ''}>
                              {c.heading_path ?? ''}
                            </span>
                            {#if date}
                              <span
                                class="flex flex-none items-center gap-1 tabular-nums"
                                title={`Event date · ${date.title}`}
                              >
                                <CalendarDays size={10} aria-hidden="true" />
                                {date.label}
                              </span>
                            {/if}
                          </div>
                        {/if}
                        <p class="whitespace-pre-wrap break-words text-foreground/90">
                          {expanded || !long ? c.text : c.text.slice(0, CHUNK_SNIPPET_CHARS) + '…'}
                        </p>
                        {#if long}
                          <button
                            type="button"
                            onclick={() => toggleChunk(c.id)}
                            class="mt-1 text-[11px] font-medium text-primary hover:underline"
                          >
                            {expanded ? 'Show less' : 'Show more'}
                          </button>
                        {/if}
                      </div>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </aside>
    {/if}
  </div>
</div>
