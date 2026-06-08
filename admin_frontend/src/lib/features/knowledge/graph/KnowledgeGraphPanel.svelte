<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { SlidersHorizontal } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
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
    GRAPH_OPTION_DEFAULTS,
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
  // Search highlight treatment of non-matches: 'highlight' (ring only) | 'dim' | 'hide'.
  let searchFocusMode = $state(savedOptions.searchFocusMode);
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

  // "Clear graph" confirm — wipes ALL entities/facts (documents/chunks are kept).
  let clearConfirmOpen = $state(false);
  let clearing = $state(false);
  async function confirmClearGraph(): Promise<void> {
    clearing = true;
    const ok = await graph.clearGraph();
    clearing = false;
    if (ok) {
      clearConfirmOpen = false;
      engine?.markIntentionalReframe();
      await graph.load(); // reflect the now-empty graph on the canvas
    }
  }

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
    const hiddenNodeTypes = graph.hiddenNodeTypes(); // tracked: a filter change is structural
    const hiddenEdgeTypes = graph.hiddenEdgeTypes(); // tracked
    if (!engine) return;
    untrack(() => engine?.setData(nodes, links, { loadVersion, hiddenNodeTypes, hiddenEdgeTypes }));
  });

  // Push the model's glow-timestamp map so the engine drives frames while halos fade.
  $effect(() => {
    engine?.setRecent(graph.recent()); // tracked
  });

  // A filter change is an intentional reframe — hand the camera back to auto-fit (the
  // setData effect sets fitPending; the engine then frames the new set on engine-stop).
  $effect(() => {
    graph.hiddenNodeTypes(); // tracked
    graph.hiddenEdgeTypes(); // tracked
    engine?.markIntentionalReframe();
  });

  // Layout-force sliders ("Link strength"/"Link distance"/"Center pull"/"Spread radius")
  // → d3 forces (engine reheats; radial ring retargets only when it actually changed).
  $effect(() => {
    const linkStrengthValue = linkStrength; // tracked
    const linkDistanceValue = linkDistance; // tracked
    const centerStrengthValue = centerStrength; // tracked
    const radialRingValue = radialRing; // tracked
    engine?.setForces({
      linkStrength: linkStrengthValue,
      linkDistance: linkDistanceValue,
      centerStrength: centerStrengthValue,
      radialRing: radialRingValue
    });
  });

  // "Edge curvature" slider → re-fan the current edges (no reheat; render-only property).
  $effect(() => {
    engine?.setCurveAmount(curveAmount); // tracked
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
      searchFocusMode
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
    searchFocusMode = GRAPH_OPTION_DEFAULTS.searchFocusMode;
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
    onFit={() => engine?.fitToView()}
    onReload={reload}
    onToggleFullscreen={toggleFullscreen}
    onClearGraph={() => (clearConfirmOpen = true)}
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

    <!-- Graph options: toggle button + dropdown. Anchored to the side OPPOSITE the detail
         aside (controlsSide) so the full-height aside never covers them. -->
    {#if graph.nodes().length > 0}
      <button
        type="button"
        onclick={() => (optionsOpen = !optionsOpen)}
        class={cn(
          'absolute top-2 z-10 rounded-md border bg-background/85 p-1.5 shadow-sm backdrop-blur transition-colors hover:bg-accent',
          controlsSide === 'left' ? 'left-2' : 'right-2',
          optionsOpen ? 'text-foreground' : 'text-muted-foreground'
        )}
        aria-label={optionsOpen ? 'Hide graph options' : 'Show graph options'}
        aria-pressed={optionsOpen}
        title="Graph options"
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
      </button>
      {#if optionsOpen}
        <div class={cn('absolute top-12 z-10', controlsSide === 'left' ? 'left-2' : 'right-2')}>
          <KnowledgeGraphOptionsPanel
            bind:linkStrength
            bind:linkDistance
            bind:centerStrength
            bind:radialRing
            bind:curveAmount
            bind:maxLinksPerPair
            bind:searchFocusMode
            centerStrengthMax={CENTER_STRENGTH_MAX}
            radialRingMin={RADIAL_RING_MIN}
            radialRingMax={RADIAL_RING_MAX}
            maxLinksCap={MAX_LINKS_CAP}
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
          'pointer-events-none absolute bottom-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur-sm',
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

<!-- Clear-graph confirm. Wipes every entity + fact; documents/chunks are kept so the
     graph can be rebuilt from the Add tab. -->
<Dialog.Root bind:open={clearConfirmOpen}>
  <Dialog.Content showCloseButton={!clearing}>
    <Dialog.Header>
      <Dialog.Title>Clear the entire knowledge graph?</Dialog.Title>
      <Dialog.Description>
        This deletes every entity and relation ({graph.nodes().length} nodes · {graph.links().length}
        edges). Your documents and their chunks are kept, so you can rebuild the graph from the Add
        tab. This can't be undone.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" disabled={clearing} onclick={() => (clearConfirmOpen = false)}>
        Cancel
      </Button>
      <Button variant="destructive" disabled={clearing} onclick={() => void confirmClearGraph()}>
        {clearing ? 'Clearing…' : 'Clear graph'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
