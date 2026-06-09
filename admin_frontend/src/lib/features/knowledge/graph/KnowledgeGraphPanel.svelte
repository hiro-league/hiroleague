<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { Maximize2, Minimize2, RefreshCw, Scan, Shuffle, SlidersHorizontal } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { cn } from '$lib/utils';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import KnowledgeGraphDetailPanel from './KnowledgeGraphDetailPanel.svelte';
  import KnowledgeGraphOptionsPanel from './KnowledgeGraphOptionsPanel.svelte';
  import KnowledgeGraphToolbar from './KnowledgeGraphToolbar.svelte';
  import { GraphCanvasEngine } from './engine/graph-canvas-engine';
  import { capParallelLinks } from './engine/graph-links';
  import { linkEndId } from './engine/graph-types';
  import {
    CENTER_STRENGTH_MAX,
    CHARGE_STRENGTH_MAX,
    CHARGE_STRENGTH_MIN,
    EDGE_LABEL_MAX_MAX,
    EDGE_LABEL_MAX_MIN,
    GRAPH_OPTION_DEFAULTS,
    LABEL_FONT_BOUND_MAX,
    LABEL_FONT_BOUND_MIN,
    LABEL_ZOOM_BOUND_MAX,
    LABEL_ZOOM_BOUND_MIN,
    MAX_LINKS_CAP,
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
  // The canvas engine owns the force-graph instance, custom drawing, force tuning, camera
  // arbitration, and redraw gating (see engine/graph-canvas-engine.ts). This panel only
  // drives it: it pushes reactive model/option reads in via the $effects below.
  let engine: GraphCanvasEngine | null = null;

  // Graph-options sliders, seeded from localStorage so a tuned layout survives reloads
  // (persisted by the $effect below; see knowledge-graph-prefs).
  const savedOptions = readGraphOptions();
  let linkStrength = $state(savedOptions.linkStrength); // d3 link-force strength: 0 loose … 1 rigid
  let linkDistance = $state(savedOptions.linkDistance); // d3 link-force resting length in px
  let centerStrength = $state(savedOptions.centerStrength); // d3 center pull: reels in drifting nodes/groups
  let radialRing = $state(savedOptions.radialRing); // outer-ring radius for least-connected/disconnected nodes
  let curveAmount = $state(savedOptions.curveAmount); // max bow for fanned parallel edges (0 = straight)
  let maxLinksPerPair = $state(savedOptions.maxLinksPerPair); // parallel edges per pair; MAX = all
  let chargeStrength = $state(savedOptions.chargeStrength); // d3 charge (node repulsion); negative
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

  function resize(): void {
    engine?.resize();
  }

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

  // The capped link set fed to the engine + the focus computation below. Recomputes when
  // the visible links change OR the "Max links per pair" control changes.
  const displayLinks = $derived(capParallelLinks(graph.visibleLinks(), maxLinksPerPair));

  // ── Search highlight aliases ────────────────────────────────────────────────
  // Local mirrors of the model's search state so the $effects below can track them.
  const searchActive = $derived(graph.searchActive());
  const matchedNodeIds = $derived(graph.matchedNodeIds());
  const matchedEdgeIds = $derived(graph.matchedEdgeIds());

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
  // non-matches in the renderer. 'hide' instead REMOVES the off-focus nodes from the data
  // fed to the engine, so the matched subset re-lays-out to fill the frame (a true
  // "recreate", matching how the type filters behave). Restores the full set the moment
  // the search clears or the mode switches away from 'hide'.
  const hideMode = $derived(searchActive && searchFocusMode === 'hide');
  const renderNodes = $derived.by(() => {
    const base = graph.visibleNodes();
    return hideMode && focusNodeIds ? base.filter((n) => focusNodeIds.has(n.id)) : base;
  });
  const renderLinks = $derived.by(() =>
    hideMode ? displayLinks.filter((l) => matchedEdgeIds.has(l.id)) : displayLinks
  );

  onMount(async () => {
    if (!container) return;
    engine = new GraphCanvasEngine({
      onNodeClick: (id) => graph.selectNode(id),
      onLinkClick: (id) => graph.selectEdge(id),
      onBackgroundClick: () => graph.clearSelection()
    });
    await engine.mount(container, {
      linkStrength,
      linkDistance,
      curveAmount,
      centerStrength,
      radialRing
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

  // ── Drive the engine from reactive model / option reads ──────────────────────

  // Recreate the graph from the render subset whenever membership, filters, OR the
  // search-focus 'hide' subset change. The engine reconciles into its durable mirrors and
  // decides structural (full relayout + fit) vs incremental delta (local settle). The
  // engine.setData call is untracked so that iterating the reactive render objects inside
  // it can't register stray per-field dependencies — the tracked reads are only the ones
  // listed below (render set / filters / reload).
  $effect(() => {
    const nodes = renderNodes; // tracked
    const links = renderLinks; // tracked
    const loadVersion = graph.loadVersion(); // tracked: structural reload signal
    const hiddenNodeIds = graph.hiddenNodeIds(); // tracked: a node-instance filter change is structural
    const hiddenEdgeTypes = graph.hiddenEdgeTypes(); // tracked
    const filterToken = graph.filterToken(); // tracked: an edge-filter change is structural too
    if (!engine) return;
    untrack(() =>
      engine?.setData(nodes, links, { loadVersion, hiddenNodeIds, hiddenEdgeTypes, filterToken })
    );
  });

  // Push the model's glow-timestamp map so the engine drives frames while halos fade.
  $effect(() => {
    engine?.setRecent(graph.recent()); // tracked
  });

  // A filter change is an intentional reframe — hand the camera back to auto-fit (the
  // setData effect sets fitPending; the engine then frames the new set on engine-stop).
  $effect(() => {
    graph.hiddenNodeIds(); // tracked
    graph.hiddenEdgeTypes(); // tracked
    graph.filterToken(); // tracked: edge filters reframe too
    engine?.markIntentionalReframe();
  });

  // Layout-force sliders ("Link strength"/"Link distance"/"Center pull"/"Spread radius")
  // → d3 forces (engine reheats; radial ring retargets only when it actually changed).
  $effect(() => {
    const linkStrengthValue = linkStrength; // tracked
    const linkDistanceValue = linkDistance; // tracked
    const centerStrengthValue = centerStrength; // tracked
    const radialRingValue = radialRing; // tracked
    const chargeStrengthValue = chargeStrength; // tracked
    engine?.setForces({
      linkStrength: linkStrengthValue,
      linkDistance: linkDistanceValue,
      centerStrength: centerStrengthValue,
      radialRing: radialRingValue,
      chargeStrength: chargeStrengthValue
    });
  });

  // "Edge curvature" slider → re-fan the current edges (no reheat; render-only property).
  $effect(() => {
    engine?.setCurveAmount(curveAmount); // tracked
  });

  // Label sizing (View → font controls) → engine repaints labels at the new zoom/size mapping.
  $effect(() => {
    engine?.setLabelSizing({
      edgeZoomMin, // tracked
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

  // Search highlight state → engine repaints rings/dim/hide and frames the matched subset.
  $effect(() => {
    engine?.setSearch({
      searchActive, // tracked
      matchedNodeIds, // tracked
      matchedEdgeIds, // tracked
      focusNodeIds, // tracked
      searchFocusMode // tracked
    });
  });

  // ── Selection (neighbor) focus ──────────────────────────────────────────────
  // When a node is selected and selectionFocusMode isn't 'all', focus its ego network (the node
  // + its directly-connected nodes/edges from the rendered set). Search WINS — this is inert while
  // a search is active. Renderer-only (no relayout) so clicking nodes stays snappy.
  const selectedNodeId = $derived(
    graph.selected()?.kind === 'node' ? (graph.selected() as { id: string }).id : null
  );
  const neighborFocus = $derived.by(() => {
    if (searchActive || selectionFocusMode === 'all' || !selectedNodeId) {
      return { active: false, mode: 'dim' as const, selectedId: '', nodeIds: new Set<string>(), edgeIds: new Set<string>() };
    }
    const nodeIds = new Set<string>([selectedNodeId]);
    const edgeIds = new Set<string>();
    for (const l of displayLinks) {
      const a = String(linkEndId(l.source));
      const b = String(linkEndId(l.target));
      if (a === selectedNodeId || b === selectedNodeId) {
        edgeIds.add(l.id);
        nodeIds.add(a);
        nodeIds.add(b);
      }
    }
    return {
      active: true,
      mode: selectionFocusMode === 'hide' ? ('hide' as const) : ('dim' as const),
      selectedId: selectedNodeId,
      nodeIds,
      edgeIds
    };
  });
  $effect(() => {
    engine?.setNeighborFocus(neighborFocus); // tracked
  });

  // Highlight the selected node/edge (blue ring/line, overrides the search highlight).
  $effect(() => {
    engine?.setSelection(graph.selected()); // tracked
  });

  // Persist the graph-options sliders to localStorage whenever any of them change (also
  // runs once on mount, writing the just-loaded values back — harmless).
  $effect(() => {
    writeGraphOptions({
      linkStrength,
      linkDistance,
      centerStrength,
      radialRing,
      curveAmount,
      maxLinksPerPair,
      chargeStrength,
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
    maxLinksPerPair = GRAPH_OPTION_DEFAULTS.maxLinksPerPair;
    chargeStrength = GRAPH_OPTION_DEFAULTS.chargeStrength;
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

  // The shared knowledge SSE is paused while this browser tab is hidden (frees the
  // per-origin connection budget so other tabs don't stall). Live deltas have no backlog,
  // so on refocus we backfill from a full re-export — but ONLY while a build is/was
  // streaming (progress set), otherwise an idle, carefully-posed graph would needlessly
  // relayout + reframe every time the user alt-tabs back.
  function onVisibilityChange(): void {
    if (document.visibilityState !== 'visible') return;
    if (graph.progress() === null) return;
    engine?.markIntentionalReframe();
    void graph.loadGroups();
    void graph.load();
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
</script>

<svelte:window onresize={resize} onkeydown={onKeydown} />
<svelte:document onvisibilitychange={onVisibilityChange} />

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
            bind:maxLinksPerPair
            bind:chargeStrength
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
            maxLinksCap={MAX_LINKS_CAP}
            chargeMin={CHARGE_STRENGTH_MIN}
            chargeMax={CHARGE_STRENGTH_MAX}
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
    <KnowledgeGraphDetailPanel {node} {edge} {graph} side={detailSide} onFlipSide={flipPanelSide} />
  </div>
</div>
