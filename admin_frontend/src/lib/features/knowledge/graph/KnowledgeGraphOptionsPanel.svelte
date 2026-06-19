<script lang="ts">
  /**
   * Left-side "Graph options" panel. Three collapsible sections (Filters → View → Physics):
   *  • Filters — edge/node visibility (validity / dates / orphans / connection caps), model-backed.
   *  • View — visual treatment that doesn't change membership (curvature, focus modes, label sizing).
   *  • Physics — live layout forces (parent owns the values, applies them to force-graph).
   * Each control carries a subtle reset (↺) shown only when it differs from its default; a global
   * Reset lives in the header. Toggled by a button in the graph's upper-left corner.
   */
  import { X } from '@lucide/svelte';
  import {
    readGraphOptionSections,
    writeGraphOptionSections,
    type SearchFocusMode,
    type SelectionFocusMode
  } from './knowledge-graph-prefs';
  import GraphOptionsFiltersSection from './options/GraphOptionsFiltersSection.svelte';
  import GraphOptionsPhysicsSection from './options/GraphOptionsPhysicsSection.svelte';
  import GraphOptionsViewSection from './options/GraphOptionsViewSection.svelte';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';

  let {
    graph,
    linkStrength = $bindable(),
    linkDistance = $bindable(),
    centerStrength = $bindable(),
    radialRing = $bindable(),
    curveAmount = $bindable(),
    chargeStrength = $bindable(),
    hubSeparation = $bindable(),
    hubSpacing = $bindable(),
    collideScale = $bindable(),
    nodeFadeStart = $bindable(),
    nodeFadeFull = $bindable(),
    nodeRevealLo = $bindable(),
    nodeRevealHi = $bindable(),
    nodeSizeMin = $bindable(),
    nodeSizeMax = $bindable(),
    searchFocusMode = $bindable(),
    selectionFocusMode = $bindable(),
    edgeZoomMin = $bindable(),
    edgeZoomMax = $bindable(),
    edgeFontMin = $bindable(),
    edgeFontMax = $bindable(),
    nodeZoomMin = $bindable(),
    nodeZoomMax = $bindable(),
    nodeFontMin = $bindable(),
    nodeFontMax = $bindable(),
    edgeLabelMax = $bindable(),
    centerStrengthMax,
    radialRingMin,
    radialRingMax,
    chargeMin,
    chargeMax,
    hubSeparationMin,
    hubSeparationMax,
    hubSpacingMin,
    hubSpacingMax,
    collideScaleMin,
    collideScaleMax,
    nodeFadeBoundMin,
    nodeFadeBoundMax,
    nodeRevealZoomMin,
    nodeRevealZoomMax,
    nodeSizeBoundMin,
    nodeSizeBoundMax,
    zoomBoundMin,
    zoomBoundMax,
    fontBoundMin,
    fontBoundMax,
    edgeLabelMaxMin,
    edgeLabelMaxMax,
    onReset,
    onClose
  }: {
    graph: KnowledgeGraphModel;
    linkStrength: number;
    linkDistance: number;
    centerStrength: number;
    radialRing: number;
    curveAmount: number;
    chargeStrength: number;
    hubSeparation: number;
    hubSpacing: number;
    collideScale: number;
    nodeFadeStart: number;
    nodeFadeFull: number;
    nodeRevealLo: number;
    nodeRevealHi: number;
    nodeSizeMin: number;
    nodeSizeMax: number;
    searchFocusMode: SearchFocusMode;
    selectionFocusMode: SelectionFocusMode;
    edgeZoomMin: number;
    edgeZoomMax: number;
    edgeFontMin: number;
    edgeFontMax: number;
    nodeZoomMin: number;
    nodeZoomMax: number;
    nodeFontMin: number;
    nodeFontMax: number;
    edgeLabelMax: number;
    centerStrengthMax: number;
    radialRingMin: number;
    radialRingMax: number;
    chargeMin: number;
    chargeMax: number;
    hubSeparationMin: number;
    hubSeparationMax: number;
    hubSpacingMin: number;
    hubSpacingMax: number;
    collideScaleMin: number;
    collideScaleMax: number;
    nodeFadeBoundMin: number;
    nodeFadeBoundMax: number;
    nodeRevealZoomMin: number;
    nodeRevealZoomMax: number;
    nodeSizeBoundMin: number;
    nodeSizeBoundMax: number;
    zoomBoundMin: number;
    zoomBoundMax: number;
    fontBoundMin: number;
    fontBoundMax: number;
    edgeLabelMaxMin: number;
    edgeLabelMaxMax: number;
    onReset: () => void;
    onClose: () => void;
  } = $props();

  const savedSections = readGraphOptionSections();
  let filtersOpen = $state(savedSections.filters);
  let viewOpen = $state(savedSections.view);
  let physicsOpen = $state(savedSections.physics);
  $effect(() => {
    writeGraphOptionSections({ filters: filtersOpen, view: viewOpen, physics: physicsOpen });
  });
</script>

<div class="flex max-h-full w-72 flex-col rounded-lg border bg-background/95 shadow-md backdrop-blur">
  <div class="flex items-center justify-between gap-2 border-b px-3 py-2">
    <h3 class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Graph options</h3>
    <div class="flex items-center gap-1">
      <button type="button" onclick={onReset} class="rounded px-1.5 py-0.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground">Reset</button>
      <button type="button" onclick={onClose} class="rounded p-0.5 text-muted-foreground hover:bg-accent" aria-label="Hide graph options">
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  </div>

  <div class="min-h-0 flex-1 space-y-3 overflow-y-auto p-2.5 [scrollbar-gutter:stable] [scrollbar-width:thin]">
    <GraphOptionsFiltersSection {graph} bind:open={filtersOpen} />
    <GraphOptionsViewSection
      bind:open={viewOpen}
      bind:curveAmount
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
      {nodeFadeBoundMin}
      {nodeFadeBoundMax}
      {nodeRevealZoomMin}
      {nodeRevealZoomMax}
      {nodeSizeBoundMin}
      {nodeSizeBoundMax}
      {zoomBoundMin}
      {zoomBoundMax}
      {fontBoundMin}
      {fontBoundMax}
      {edgeLabelMaxMin}
      {edgeLabelMaxMax}
    />
    <GraphOptionsPhysicsSection
      bind:open={physicsOpen}
      bind:linkStrength
      bind:linkDistance
      bind:centerStrength
      bind:radialRing
      bind:chargeStrength
      bind:hubSeparation
      bind:hubSpacing
      bind:collideScale
      {centerStrengthMax}
      {radialRingMin}
      {radialRingMax}
      {chargeMin}
      {chargeMax}
      {hubSeparationMin}
      {hubSeparationMax}
      {hubSpacingMin}
      {hubSpacingMax}
      {collideScaleMin}
      {collideScaleMax}
    />
  </div>
</div>
