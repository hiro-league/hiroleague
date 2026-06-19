<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { createGraphFullscreenLifecycle } from '../shared/graph-fullscreen';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { cn } from '$lib/utils';
  import Button from '$lib/components/ui/button.svelte';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { createGraphEngineBridge } from '../state/graph/graph-engine-bridge.svelte';
  import { createGraphOptionsState } from '../state/graph/create-graph-options-state.svelte';
  import KnowledgeGraphDetailPanel from './KnowledgeGraphDetailPanel.svelte';
  import KnowledgeGraphOptionsPanel from './KnowledgeGraphOptionsPanel.svelte';
  import KnowledgeGraphToolbar from './KnowledgeGraphToolbar.svelte';
  import GraphCanvasControls from './GraphCanvasControls.svelte';
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
    readGraphPanelSide,
    writeGraphPanelSide
  } from './knowledge-graph-prefs';

  interface Props {
    graph: KnowledgeGraphModel;
  }
  let { graph }: Props = $props();

  let container = $state<HTMLDivElement | null>(null);
  // $state so the graph-engine-bridge option effects (node fade, label sizing, forces, …)
  // re-run and push their values once the engine is assigned. Assigned AFTER mount() below.
  let engine = $state<GraphCanvasEngine | null>(null);

  const graphOptions = createGraphOptionsState({
    resetEdgeFilters: () => graph.resetEdgeFilters()
  });

  let optionsOpen = $state(false);

  let panelSide = $state(readGraphPanelSide());
  const detailSide = $derived(
    panelSide === 'auto' ? (chatOverlay.open ? 'left' : 'right') : panelSide
  );
  const controlsSide = $derived(detailSide === 'left' ? 'right' : 'left');

  function flipPanelSide(): void {
    panelSide = detailSide === 'left' ? 'right' : 'left';
  }

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

  function previewConnection(sel: { kind: 'node' | 'edge'; id: string } | null): void {
    engine?.setPreview(sel);
  }

  $effect(() => {
    writeGraphPanelSide(panelSide);
  });

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
      linkStrength: graphOptions.linkStrength,
      linkDistance: graphOptions.linkDistance,
      centerStrength: graphOptions.centerStrength,
      radialRing: graphOptions.radialRing,
      chargeStrength: graphOptions.chargeStrength,
      hubSeparation: graphOptions.hubSeparation,
      hubSpacing: graphOptions.hubSpacing,
      collideScale: graphOptions.collideScale
    }),
    getCurveAmount: () => graphOptions.curveAmount,
    getNodeSizing: () => ({
      minSize: graphOptions.nodeSizeMin,
      maxSize: graphOptions.nodeSizeMax
    }),
    getLabelSizing: () => ({
      edgeZoomMin: graphOptions.edgeZoomMin,
      edgeZoomMax: graphOptions.edgeZoomMax,
      edgeFontMin: graphOptions.edgeFontMin,
      edgeFontMax: graphOptions.edgeFontMax,
      nodeZoomMin: graphOptions.nodeZoomMin,
      nodeZoomMax: graphOptions.nodeZoomMax,
      nodeFontMin: graphOptions.nodeFontMin,
      nodeFontMax: graphOptions.nodeFontMax,
      edgeLabelMax: graphOptions.edgeLabelMax
    }),
    getNodeFade: () => ({
      nodeFadeStart: graphOptions.nodeFadeStart,
      nodeFadeFull: graphOptions.nodeFadeFull,
      nodeRevealLo: graphOptions.nodeRevealLo,
      nodeRevealHi: graphOptions.nodeRevealHi
    }),
    getSearchFocusMode: () => graphOptions.searchFocusMode,
    getSelectionFocusMode: () => graphOptions.selectionFocusMode
  });

  let zoomLevel = $state(1);

  onMount(() => graphFullscreen.mount());

  onMount(async () => {
    if (!container) return;
    const e = new GraphCanvasEngine({
      onNodeClick: (id) => graph.selectNode(id),
      onLinkClick: (id) => graph.selectEdge(id),
      onBackgroundClick: () => graph.clearSelection(),
      onZoomChange: (k) => (zoomLevel = k)
    });
    await e.mount(container, {
      linkStrength: graphOptions.linkStrength,
      linkDistance: graphOptions.linkDistance,
      curveAmount: graphOptions.curveAmount,
      centerStrength: graphOptions.centerStrength,
      radialRing: graphOptions.radialRing,
      hubSeparation: graphOptions.hubSeparation,
      hubSpacing: graphOptions.hubSpacing,
      collideScale: graphOptions.collideScale,
      nodeSizeMin: graphOptions.nodeSizeMin,
      nodeSizeMax: graphOptions.nodeSizeMax
    });
    // Publish the engine only after mount() resolves: assigning the $state re-runs the
    // bridge effects, which now push fade/label/forces/etc. to a fully-mounted engine.
    engine = e;
    await graph.loadGroups();
    await graph.load();
    void graph.loadPreferences();
  });

  function selectGroup(id: string): void {
    engine?.markIntentionalReframe();
    void graph.selectGroup(id);
  }

  function reload(): void {
    engine?.markIntentionalReframe();
    void graph.load();
  }

  function redraw(): void {
    engine?.relayout();
  }

  function reframeForSearch(): void {
    engine?.markIntentionalReframe();
  }

  onDestroy(() => {
    engine?.destroy();
    engine = null;
  });

  const node = $derived(graph.selectedNode());
  const edge = $derived(graph.selectedEdge());
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

<div
  class={cn(
    'flex flex-col',
    fullscreen ? 'fixed inset-0 z-30 overflow-hidden bg-background' : 'gap-3'
  )}
  style={fullscreen
    ? undefined
    : 'min-height: calc(100vh - 4rem - var(--admin-page-header-h, 150px) - 3rem)'}
>
  <KnowledgeGraphToolbar
    {graph}
    {fullscreen}
    onSelectGroup={selectGroup}
    onSearchReframe={reframeForSearch}
  />

  <div
    class={cn(
      'relative flex-1 overflow-hidden bg-background',
      !fullscreen && 'rounded-lg border'
    )}
  >
    <div bind:this={container} class="absolute inset-0"></div>

    <GraphCanvasControls
      controlsSide={controlsSide}
      showGraphControls={graph.nodes().length > 0}
      optionsOpen={optionsOpen}
      loading={graph.loading()}
      {fullscreen}
      onToggleOptions={() => (optionsOpen = !optionsOpen)}
      onRedraw={redraw}
      onFit={() => engine?.fitToView()}
      onReload={reload}
      onToggleFullscreen={toggleFullscreen}
    />

    {#if graph.nodes().length > 0}
      {#if optionsOpen}
        <div class={cn('absolute top-12 bottom-12 z-10', controlsSide === 'left' ? 'left-2' : 'right-2')}>
          <KnowledgeGraphOptionsPanel
            {graph}
            bind:linkStrength={graphOptions.linkStrength}
            bind:linkDistance={graphOptions.linkDistance}
            bind:centerStrength={graphOptions.centerStrength}
            bind:radialRing={graphOptions.radialRing}
            bind:curveAmount={graphOptions.curveAmount}
            bind:chargeStrength={graphOptions.chargeStrength}
            bind:hubSeparation={graphOptions.hubSeparation}
            bind:hubSpacing={graphOptions.hubSpacing}
            bind:collideScale={graphOptions.collideScale}
            bind:nodeFadeStart={graphOptions.nodeFadeStart}
            bind:nodeFadeFull={graphOptions.nodeFadeFull}
            bind:nodeRevealLo={graphOptions.nodeRevealLo}
            bind:nodeRevealHi={graphOptions.nodeRevealHi}
            bind:nodeSizeMin={graphOptions.nodeSizeMin}
            bind:nodeSizeMax={graphOptions.nodeSizeMax}
            bind:searchFocusMode={graphOptions.searchFocusMode}
            bind:selectionFocusMode={graphOptions.selectionFocusMode}
            bind:edgeZoomMin={graphOptions.edgeZoomMin}
            bind:edgeZoomMax={graphOptions.edgeZoomMax}
            bind:edgeFontMin={graphOptions.edgeFontMin}
            bind:edgeFontMax={graphOptions.edgeFontMax}
            bind:nodeZoomMin={graphOptions.nodeZoomMin}
            bind:nodeZoomMax={graphOptions.nodeZoomMax}
            bind:nodeFontMin={graphOptions.nodeFontMin}
            bind:nodeFontMax={graphOptions.nodeFontMax}
            bind:edgeLabelMax={graphOptions.edgeLabelMax}
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
            onReset={() => graphOptions.reset()}
            onClose={() => (optionsOpen = false)}
          />
        </div>
      {/if}
    {/if}

    {#if graph.nodes().length === 0 && !graph.loading()}
      <div class="absolute inset-0 grid place-items-center p-6">
        {#if graph.loadError()}
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
