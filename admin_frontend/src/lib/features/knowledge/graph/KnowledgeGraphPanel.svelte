<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { createGraphFullscreenLifecycle } from '../shared/graph-fullscreen';
  import { Maximize2, Minimize2, RefreshCw, Scan, Shuffle, SlidersHorizontal } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { cn } from '$lib/utils';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { createGraphEngineBridge } from '../state/graph/graph-engine-bridge.svelte';
  import KnowledgeGraphDetailPanel from './KnowledgeGraphDetailPanel.svelte';
  import KnowledgeGraphOptionsPanel from './KnowledgeGraphOptionsPanel.svelte';
  import KnowledgeGraphToolbar from './KnowledgeGraphToolbar.svelte';
  import { GraphCanvasEngine } from './engine/graph-canvas-engine';
  import { collapseParallelLinks } from './engine/graph-links';
  import { linkEndId } from './engine/graph-types';
  import { VISIBLE_EDGES_CAP } from '../state/knowledge-graph.svelte';
  import {
    CENTER_STRENGTH_MAX,
    CHARGE_STRENGTH_MAX,
    CHARGE_STRENGTH_MIN,
    EDGE_LABEL_MAX_MAX,
    EDGE_LABEL_MAX_MIN,
    GRAPH_OPTION_DEFAULTS,
    HUB_SEPARATION_MAX,
    HUB_SEPARATION_MIN,
    HUB_SPACING_MAX,
    HUB_SPACING_MIN,
    COLLIDE_SCALE_MAX,
    COLLIDE_SCALE_MIN,
    NODE_FADE_MAX,
    NODE_FADE_MIN,
    NODE_REVEAL_ZOOM_MAX,
    NODE_REVEAL_ZOOM_MIN,
    NODE_SIZE_BOUND_MAX,
    NODE_SIZE_BOUND_MIN,
    LABEL_FONT_BOUND_MAX,
    LABEL_FONT_BOUND_MIN,
    LABEL_ZOOM_BOUND_MAX,
    LABEL_ZOOM_BOUND_MIN,
    RADIAL_RING_MAX,
    RADIAL_RING_MIN,
    readGraphOptions,
    readGraphPanelSide,
    writeGraphOptions,
    writeGraphPanelSide
  } from './knowledge-graph-prefs';

  interface Props {
    graph: KnowledgeGraphModel;
  }
  let { graph }: Props = $props();

  // Node mount point for force-graph (it appends its own <canvas>).
  let container = $state<HTMLDivElement | null>(null);
  // The canvas engine owns force-graph; model↔engine sync lives in graph-engine-bridge.svelte.ts.
  let engine: GraphCanvasEngine | null = null;

  // Graph-options sliders, seeded from localStorage so a tuned layout survives reloads
  // (persisted by the $effect below; see knowledge-graph-prefs).
  const savedOptions = readGraphOptions();
  let linkStrength = $state(savedOptions.linkStrength); // d3 link-force strength: 0 loose … 1 rigid
  let linkDistance = $state(savedOptions.linkDistance); // d3 link-force resting length in px
  let centerStrength = $state(savedOptions.centerStrength); // d3 center pull: reels in drifting nodes/groups
  let radialRing = $state(savedOptions.radialRing); // outer-ring radius for least-connected/disconnected nodes
  let curveAmount = $state(savedOptions.curveAmount); // max bow for fanned parallel edges (0 = straight)
  let chargeStrength = $state(savedOptions.chargeStrength); // d3 charge (node repulsion); negative
  let hubSeparation = $state(savedOptions.hubSeparation); // pushes high-degree hubs apart (0 = off)
  let hubSpacing = $state(savedOptions.hubSpacing); // how far hubs spread (multiplier; inert at sep 0)
  let collideScale = $state(savedOptions.collideScale); // collide-radius multiplier (label-spacing knob)
  let nodeFadeStart = $state(savedOptions.nodeFadeStart); // "Node fade" range: prominence → fully transparent
  let nodeFadeFull = $state(savedOptions.nodeFadeFull); // → fully solid (full ≤ start disables fade)
  let nodeRevealLo = $state(savedOptions.nodeRevealLo); // zoom-reveal: hazy below this zoom…
  let nodeRevealHi = $state(savedOptions.nodeRevealHi); // …clear above this zoom (hi ≤ lo = static)
  let nodeSizeMin = $state(savedOptions.nodeSizeMin); // degree-based node radius: least-connected
  let nodeSizeMax = $state(savedOptions.nodeSizeMax); // most-connected (font scales with size too)
  // Search highlight treatment of non-matches: 'highlight' (ring only) | 'dim' | 'hide'.
  let searchFocusMode = $state(savedOptions.searchFocusMode);
  // Selected-node focus: 'all' (off) | 'dim' others | 'hide' others. Search wins when both active.
  let selectionFocusMode = $state(savedOptions.selectionFocusMode);
  // Live label sizing (View → font controls) — zoom thresholds + font px ranges per text type,
  // plus the edge-label trim length. Seeded from persisted options; pushed to the engine below.
  let edgeZoomMin = $state(savedOptions.edgeZoomMin);
  let edgeZoomMax = $state(savedOptions.edgeZoomMax);
  let edgeFontMin = $state(savedOptions.edgeFontMin);
  let edgeFontMax = $state(savedOptions.edgeFontMax);
  let nodeZoomMin = $state(savedOptions.nodeZoomMin);
  let nodeZoomMax = $state(savedOptions.nodeZoomMax);
  let nodeFontMin = $state(savedOptions.nodeFontMin);
  let nodeFontMax = $state(savedOptions.nodeFontMax);
  let edgeLabelMax = $state(savedOptions.edgeLabelMax);
  let optionsOpen = $state(false);

  // Which side the selection/detail aside docks on. 'auto' (default) follows the chat
  // overlay so the panel is never hidden behind it (chat docks right): left while chat is
  // open, right otherwise. 'left'/'right' pin it explicitly (set via the flip button in the
  // panel header). Persisted to localStorage by the $effect below.
  let panelSide = $state(readGraphPanelSide());
  const detailSide = $derived(
    panelSide === 'auto' ? (chatOverlay.open ? 'left' : 'right') : panelSide
  );
  // The graph-options button/dropdown and the stats overlay always sit on the side OPPOSITE
  // the detail aside, so the full-height aside can never cover them (req: options stay
  // reachable when the panel is on the left).
  const controlsSide = $derived(detailSide === 'left' ? 'right' : 'left');

  // The flip button in the detail header pins the panel to the opposite of where it
  // currently shows (an explicit choice that overrides 'auto').
  function flipPanelSide(): void {
    panelSide = detailSide === 'left' ? 'right' : 'left';
  }

  // Detail-panel "click a connection" → select it AND slide the camera to centre it (an edge
  // centres on its two endpoints). The graph stays put on a normal canvas click; only panel
  // navigation recentres, so the thing you just jumped to is brought into view.
  function navigateToSelection(sel: { kind: 'node' | 'edge'; id: string }): void {
    if (sel.kind === 'node') {
      graph.selectNode(sel.id);
      engine?.centerOn([sel.id]);
    } else {
      graph.selectEdge(sel.id);
      const e = graph.links().find((l) => l.id === sel.id);
      engine?.centerOn(e ? [String(e.source), String(e.target)] : []);
    }
  }

  // Detail-panel "hover a connection" → transiently ring it on the canvas (no selection). The
  // panel clears it (null) on mouse-leave / teardown. The id may be an aggregate edge's id; the
  // engine resolves it against its own mirror links.
  function previewConnection(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    engine?.setPreview(sel);
  }

  // Persist the dock-side preference whenever it changes (also runs once on mount).
  $effect(() => {
    writeGraphPanelSide(panelSide);
  });

  // Fullscreen: the expand button lifts the panel to a true full-viewport overlay
  // (position:fixed inset-0, above the shell) so the graph gets the whole screen. Esc — or
  // the minimize button — returns to the default in-flow layout. The default view already
  // fills the content area below the knowledge header, which is forced compact for the
  // Graph tab (KnowledgePage passes forceCompact) so the canvas has room.
  let fullscreen = $state(false);

  const graphFullscreen = createGraphFullscreenLifecycle({
    getFullscreen: () => fullscreen,
    setFullscreen: (value) => {
      fullscreen = value;
    },
    onResize: () => engine?.resize(),
    onVisibilityVisible: () => {
      if (graph.progress() === null) return;
      engine?.markIntentionalReframe();
      void graph.loadGroups();
      void graph.load();
    }
  });
  const { toggleFullscreen } = graphFullscreen;

  // The display link set fed to the engine + the focus computation below. Collapses each entity
  // pair's parallel edges past the "Visible edges" cap into one "N other relations" aggregate edge
  // (kept edges chosen by "Keep which connections"). Recomputes when the visible links change OR
  // either of those model settings changes.
  const displayLinks = $derived(
    collapseParallelLinks(
      graph.visibleLinks(),
      graph.visibleEdgesPerPair(),
      graph.maxConnBy(),
      VISIBLE_EDGES_CAP
    )
  );

  createGraphEngineBridge({
    getGraph: () => graph,
    getEngine: () => engine,
    getDisplayLinks: () => displayLinks,
    getForceOptions: () => ({
      linkStrength,
      linkDistance,
      centerStrength,
      radialRing,
      chargeStrength,
      hubSeparation,
      hubSpacing,
      collideScale
    }),
    getCurveAmount: () => curveAmount,
    getNodeSizing: () => ({ minSize: nodeSizeMin, maxSize: nodeSizeMax }),
    getLabelSizing: () => ({
      edgeZoomMin,
      edgeZoomMax,
      edgeFontMin,
      edgeFontMax,
      nodeZoomMin,
      nodeZoomMax,
      nodeFontMin,
      nodeFontMax,
      edgeLabelMax
    }),
    getNodeFade: () => ({
      nodeFadeStart,
      nodeFadeFull,
      nodeRevealLo,
      nodeRevealHi
    }),
    getSearchFocusMode: () => searchFocusMode,
    getSelectionFocusMode: () => selectionFocusMode
  });

  let zoomLevel = $state(1);

  onMount(() => graphFullscreen.mount());

  onMount(async () => {
    if (!container) return;
    engine = new GraphCanvasEngine({
      onNodeClick: (id) => graph.selectNode(id),
      onLinkClick: (id) => graph.selectEdge(id),
      onBackgroundClick: () => graph.clearSelection(),
      onZoomChange: (k) => (zoomLevel = k)
    });
    await engine.mount(container, {
      linkStrength,
      linkDistance,
      curveAmount,
      centerStrength,
      radialRing,
      hubSeparation,
      hubSpacing,
      collideScale,
      nodeSizeMin,
      nodeSizeMax
    });
    // Resolve the partition list + active group FIRST (default = first in list, or the
    // remembered one), so the initial paint scopes to a group that actually has data rather
    // than the possibly-empty backend default. The LIVE SSE subscription is owned by the page
    // controller (knowledge-controller.svelte.ts), NOT here — so deltas emitted during a
    // build that started while this tab was closed are already in the model when we mount.
    await graph.loadGroups();
    await graph.load();
    // Load the admin graph-viz display preference (large-type warning threshold). Non-blocking —
    // the filter dropdowns work with the default until it resolves.
    void graph.loadPreferences();
  });

  // Switch the viewed partition — an intentional reframe so the new group's graph fits.
  function selectGroup(id: string): void {
    engine?.markIntentionalReframe();
    void graph.selectGroup(id);
  }

  // Persist the graph-options sliders to localStorage whenever any of them change (also
  // runs once on mount, writing the just-loaded values back — harmless).
  $effect(() => {
    writeGraphOptions({
      linkStrength,
      linkDistance,
      centerStrength,
      radialRing,
      curveAmount,
      chargeStrength,
      hubSeparation,
      hubSpacing,
      collideScale,
      nodeFadeStart,
      nodeFadeFull,
      nodeRevealLo,
      nodeRevealHi,
      nodeSizeMin,
      nodeSizeMax,
      searchFocusMode,
      selectionFocusMode,
      edgeZoomMin,
      edgeZoomMax,
      edgeFontMin,
      edgeFontMax,
      nodeZoomMin,
      nodeZoomMax,
      nodeFontMin,
      nodeFontMax,
      edgeLabelMax
    });
  });

  // "Reset" in the options panel → restore slider defaults (the $effect above then
  // re-persists them). Filters have their own "Clear filters" control.
  function resetGraphOptions(): void {
    linkStrength = GRAPH_OPTION_DEFAULTS.linkStrength;
    linkDistance = GRAPH_OPTION_DEFAULTS.linkDistance;
    centerStrength = GRAPH_OPTION_DEFAULTS.centerStrength;
    radialRing = GRAPH_OPTION_DEFAULTS.radialRing;
    curveAmount = GRAPH_OPTION_DEFAULTS.curveAmount;
    chargeStrength = GRAPH_OPTION_DEFAULTS.chargeStrength;
    hubSeparation = GRAPH_OPTION_DEFAULTS.hubSeparation;
    hubSpacing = GRAPH_OPTION_DEFAULTS.hubSpacing;
    collideScale = GRAPH_OPTION_DEFAULTS.collideScale;
    nodeFadeStart = GRAPH_OPTION_DEFAULTS.nodeFadeStart;
    nodeFadeFull = GRAPH_OPTION_DEFAULTS.nodeFadeFull;
    nodeRevealLo = GRAPH_OPTION_DEFAULTS.nodeRevealLo;
    nodeRevealHi = GRAPH_OPTION_DEFAULTS.nodeRevealHi;
    nodeSizeMin = GRAPH_OPTION_DEFAULTS.nodeSizeMin;
    nodeSizeMax = GRAPH_OPTION_DEFAULTS.nodeSizeMax;
    searchFocusMode = GRAPH_OPTION_DEFAULTS.searchFocusMode;
    selectionFocusMode = GRAPH_OPTION_DEFAULTS.selectionFocusMode;
    edgeZoomMin = GRAPH_OPTION_DEFAULTS.edgeZoomMin;
    edgeZoomMax = GRAPH_OPTION_DEFAULTS.edgeZoomMax;
    edgeFontMin = GRAPH_OPTION_DEFAULTS.edgeFontMin;
    edgeFontMax = GRAPH_OPTION_DEFAULTS.edgeFontMax;
    nodeZoomMin = GRAPH_OPTION_DEFAULTS.nodeZoomMin;
    nodeZoomMax = GRAPH_OPTION_DEFAULTS.nodeZoomMax;
    nodeFontMin = GRAPH_OPTION_DEFAULTS.nodeFontMin;
    nodeFontMax = GRAPH_OPTION_DEFAULTS.nodeFontMax;
    edgeLabelMax = GRAPH_OPTION_DEFAULTS.edgeLabelMax;
    graph.resetEdgeFilters(); // "Reset to defaults" clears the Filters section too
  }

  // ── Toolbar actions (engine-owned; search orchestration lives in the model) ──────
  // A reload should reframe the fresh data, so hand the camera back to auto-fit first.
  function reload(): void {
    engine?.markIntentionalReframe();
    void graph.load();
  }
  // Redraw = re-run the force layout on the CURRENT in-memory (filtered) data, no server fetch.
  function redraw(): void {
    engine?.relayout();
  }

  // Shared style for the floating canvas control buttons (Options · Redraw · Fit · Reload · Fullscreen).
  const ctrlBtn =
    'rounded-md border bg-background/85 p-1.5 text-muted-foreground shadow-sm backdrop-blur transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50 disabled:hover:bg-background/85';
  // Called by the toolbar before any query change (type / clear): a new or cleared search
  // is an intentional reframe → re-enable the focus fit so the engine frames the new set.
  function reframeForSearch(): void {
    engine?.markIntentionalReframe();
  }

  onDestroy(() => {
    // NOTE: the graph SSE subscription AND the search orchestration are owned by the page
    // controller / model, so we do NOT tear them down here — leaving the Graph tab must not
    // stop live deltas accumulating or abort a search whose highlight should persist.
    engine?.destroy();
    engine = null;
  });

  const node = $derived(graph.selectedNode());
  const edge = $derived(graph.selectedEdge());
  // A selected "N other relations" aggregate edge is synthetic (not a real GraphEdgeDTO), so
  // selectedEdge() returns null for it. Resolve it from displayLinks (where collapse runs) and
  // hand the detail panel its folded edge ids so it can show all the relations behind it.
  const selectedAggregate = $derived.by(() => {
    const sel = graph.selected();
    if (sel?.kind !== 'edge' || node || edge) return null;
    const agg = displayLinks.find((l) => 'aggregate' in l && l.aggregate && l.id === sel.id);
    return agg && 'collapsedIds' in agg
      ? {
          id: agg.id,
          source: String(linkEndId(agg.source)),
          target: String(linkEndId(agg.target)),
          collapsedIds: agg.collapsedIds,
          whole: agg.whole
        }
      : null;
  });
</script>

<!--
  Two layouts:

  Default (in-flow): a flex column that fills the content area below the knowledge header.
    The header is forced compact on the Graph tab (KnowledgePage → forceCompact),
    publishing a small --admin-page-header-h, so this min-height calc gives the canvas
    almost the whole viewport without any scroll trickery.

  Fullscreen (expand button): a true full-viewport overlay — position:fixed inset-0 above
    the shell (z-30). Covers the sidebar + header (z-20) so the graph owns the whole screen,
    while staying BELOW the floating chat overlay (z-40) and modal dialogs (z-50) so chat
    can stay on top in fullscreen. Esc or the minimize button returns to the default.
-->
<div
  class={cn(
    'flex flex-col',
    fullscreen ? 'fixed inset-0 z-30 overflow-hidden bg-background' : 'gap-3'
  )}
  style={fullscreen
    ? undefined
    : 'min-height: calc(100vh - 4rem - var(--admin-page-header-h, 150px) - 3rem)'}
>
  <!-- Top control row: filter strip + search + Fit / Reload / Fullscreen. Node/edge counts
       and live status live inside the canvas (bottom-left overlay), not here. -->
  <KnowledgeGraphToolbar
    {graph}
    {fullscreen}
    onSelectGroup={selectGroup}
    onSearchReframe={reframeForSearch}
  />

  <!-- Canvas surface. In fullscreen it fills the rest of the fixed wrapper edge-to-edge.
       In the default layout it's a bordered card matching the page's other cards. -->
  <div
    class={cn(
      'relative flex-1 overflow-hidden bg-background',
      !fullscreen && 'rounded-lg border'
    )}
  >
    <div bind:this={container} class="absolute inset-0"></div>

    <!-- Floating canvas controls: Options · Redraw · Fit · Reload · Fullscreen. Anchored to the
         side OPPOSITE the detail aside (controlsSide). Options/Redraw/Fit need a graph; Reload and
         Fullscreen stay available even when it's empty. -->
    <div
      class={cn(
        'absolute top-2 z-10 flex items-center gap-1',
        controlsSide === 'left' ? 'left-2' : 'right-2'
      )}
    >
      {#if graph.nodes().length > 0}
        <button
          type="button"
          onclick={() => (optionsOpen = !optionsOpen)}
          class={cn(ctrlBtn, optionsOpen && 'text-foreground')}
          aria-label={optionsOpen ? 'Hide graph options' : 'Show graph options'}
          aria-pressed={optionsOpen}
          title="Graph options"
        >
          <SlidersHorizontal size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          onclick={redraw}
          class={ctrlBtn}
          aria-label="Redraw layout with current filters"
          title="Redraw — re-run the layout on the current (filtered) graph"
        >
          <Shuffle size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          onclick={() => engine?.fitToView()}
          class={ctrlBtn}
          aria-label="Fit graph to view"
          title="Fit to view"
        >
          <Scan size={16} aria-hidden="true" />
        </button>
      {/if}
      <button
        type="button"
        onclick={reload}
        disabled={graph.loading()}
        class={ctrlBtn}
        aria-label="Reload graph from server"
        title="Reload — re-fetch the graph from the server"
      >
        <RefreshCw size={16} class={graph.loading() ? 'animate-spin' : ''} aria-hidden="true" />
      </button>
      <button
        type="button"
        onclick={toggleFullscreen}
        class={ctrlBtn}
        aria-label={fullscreen ? 'Exit full screen (Esc)' : 'View graph full screen'}
        title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}
      >
        {#if fullscreen}
          <Minimize2 size={16} aria-hidden="true" />
        {:else}
          <Maximize2 size={16} aria-hidden="true" />
        {/if}
      </button>
    </div>
    {#if graph.nodes().length > 0}
      {#if optionsOpen}
        <!-- top-12..bottom-12 bounds the panel to the canvas card (the card is overflow-hidden, so a
             viewport-tall panel would clip its lower rows) AND leaves the bottom-left stats overlay
             uncovered so node/edge/live counts stay visible while options are open. -->
        <div class={cn('absolute top-12 bottom-12 z-10', controlsSide === 'left' ? 'left-2' : 'right-2')}>
          <KnowledgeGraphOptionsPanel
            {graph}
            bind:linkStrength
            bind:linkDistance
            bind:centerStrength
            bind:radialRing
            bind:curveAmount
            bind:chargeStrength
            bind:hubSeparation
            bind:hubSpacing
            bind:collideScale
            bind:nodeFadeStart
            bind:nodeFadeFull
            bind:nodeRevealLo
            bind:nodeRevealHi
            bind:nodeSizeMin
            bind:nodeSizeMax
            bind:searchFocusMode
            bind:selectionFocusMode
            bind:edgeZoomMin
            bind:edgeZoomMax
            bind:edgeFontMin
            bind:edgeFontMax
            bind:nodeZoomMin
            bind:nodeZoomMax
            bind:nodeFontMin
            bind:nodeFontMax
            bind:edgeLabelMax
            centerStrengthMax={CENTER_STRENGTH_MAX}
            radialRingMin={RADIAL_RING_MIN}
            radialRingMax={RADIAL_RING_MAX}
            chargeMin={CHARGE_STRENGTH_MIN}
            chargeMax={CHARGE_STRENGTH_MAX}
            hubSeparationMin={HUB_SEPARATION_MIN}
            hubSeparationMax={HUB_SEPARATION_MAX}
            hubSpacingMin={HUB_SPACING_MIN}
            hubSpacingMax={HUB_SPACING_MAX}
            collideScaleMin={COLLIDE_SCALE_MIN}
            collideScaleMax={COLLIDE_SCALE_MAX}
            nodeFadeBoundMin={NODE_FADE_MIN}
            nodeFadeBoundMax={NODE_FADE_MAX}
            nodeRevealZoomMin={NODE_REVEAL_ZOOM_MIN}
            nodeRevealZoomMax={NODE_REVEAL_ZOOM_MAX}
            nodeSizeBoundMin={NODE_SIZE_BOUND_MIN}
            nodeSizeBoundMax={NODE_SIZE_BOUND_MAX}
            zoomBoundMin={LABEL_ZOOM_BOUND_MIN}
            zoomBoundMax={LABEL_ZOOM_BOUND_MAX}
            fontBoundMin={LABEL_FONT_BOUND_MIN}
            fontBoundMax={LABEL_FONT_BOUND_MAX}
            edgeLabelMaxMin={EDGE_LABEL_MAX_MIN}
            edgeLabelMaxMax={EDGE_LABEL_MAX_MAX}
            onReset={resetGraphOptions}
            onClose={() => (optionsOpen = false)}
          />
        </div>
      {/if}
    {/if}

    {#if graph.nodes().length === 0 && !graph.loading()}
      <div class="absolute inset-0 grid place-items-center p-6">
        {#if graph.loadError()}
          <!-- A load that FAILED (timeout / server busy / network) must not masquerade as an
               empty graph — show what went wrong + a Retry so the user isn't left guessing. -->
          <InlineEmptyState
            message="Couldn’t load the graph."
            hint={graph.loadError() ?? undefined}
          >
            {#snippet actions()}
              <Button variant="outline" size="sm" onclick={reload} disabled={graph.loading()}>
                Retry
              </Button>
            {/snippet}
          </InlineEmptyState>
        {:else if graph.progress()}
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

    <!-- Stats overlay (bottom-left, inside the graph view): node/edge counts + live/ingest
         status. Shows visible/total when a filter is active. Type legend lives in the
         filter strip above (color dots on node chips). -->
    {#if graph.nodes().length > 0}
      <div
        class={cn(
          'pointer-events-none absolute bottom-2 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur-sm',
          controlsSide === 'left' ? 'left-2' : 'right-2'
        )}
      >
        {#if graph.hasActiveFilters()}
          <span
            >{graph.visibleNodeCount()}/{graph.nodes().length} nodes · {graph.visibleEdgeCount()}/{graph.links()
              .length} edges</span
          >
        {:else}
          <span>{graph.nodes().length} nodes · {graph.links().length} edges</span>
        {/if}
        <span class="tabular-nums" title="Current zoom — match this against the label zoom thresholds in Options → View">
          {zoomLevel.toFixed(2)}×
        </span>
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

    <!-- Selection / provenance detail panel (docks left or right; flip button in its header). -->
    <KnowledgeGraphDetailPanel
      {node}
      {edge}
      aggregateEdge={selectedAggregate}
      {graph}
      side={detailSide}
      onFlipSide={flipPanelSide}
      onNavigate={navigateToSelection}
      onPreview={previewConnection}
    />
  </div>
</div>
