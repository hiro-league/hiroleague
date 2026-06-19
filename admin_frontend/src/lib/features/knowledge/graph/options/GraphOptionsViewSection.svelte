<script lang="ts">
  import { ChevronDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { GRAPH_OPTION_DEFAULTS as D, type SearchFocusMode, type SelectionFocusMode } from '../knowledge-graph-prefs';
  import GraphOptionsButtonGroup from './GraphOptionsButtonGroup.svelte';
  import GraphOptionsRangeField from './GraphOptionsRangeField.svelte';
  import GraphOptionsScalarField from './GraphOptionsScalarField.svelte';

  let {
    open = $bindable(true),
    curveAmount = $bindable(),
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
    edgeLabelMaxMax
  }: {
    open?: boolean;
    curveAmount: number;
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
  } = $props();

  const FOCUS_MODES: { value: SearchFocusMode; label: string; title: string }[] = [
    { value: 'highlight', label: 'Ring', title: 'Ring matches only; leave the rest unchanged' },
    { value: 'dim', label: 'Dim', title: 'Fade non-matching nodes and edges' },
    { value: 'hide', label: 'Hide', title: 'Hide non-matching nodes and edges' }
  ];
  const SELECTION_MODES: { value: SelectionFocusMode; label: string; title: string }[] = [
    { value: 'all', label: 'All', title: 'No focus when a node is selected' },
    { value: 'dim', label: 'Dim', title: 'Fade everything except the selected node and its neighbors' },
    { value: 'hide', label: 'Hide', title: 'Hide everything except the selected node and its neighbors' }
  ];

  const r1 = (v: number): number => Math.round(v * 10) / 10;
</script>

<section class="overflow-hidden rounded-lg border border-primary/40">
  <button
    type="button"
    onclick={() => (open = !open)}
    aria-expanded={open}
    class={cn(
      'flex w-full items-center justify-between bg-primary/20 px-2.5 py-1.5 text-xs font-semibold text-foreground',
      open && 'border-b border-primary/40'
    )}
  >
    <span>View</span>
    <ChevronDown size={14} class={cn('transition-transform', open || 'rotate-180')} aria-hidden="true" />
  </button>
  {#if open}
    <div class="space-y-3 p-2.5">
      <GraphOptionsRangeField
        title="Node size"
        dirty={nodeSizeMin !== D.nodeSizeMin || nodeSizeMax !== D.nodeSizeMax}
        onReset={() => {
          nodeSizeMin = D.nodeSizeMin;
          nodeSizeMax = D.nodeSizeMax;
        }}
        min={nodeSizeBoundMin}
        max={nodeSizeBoundMax}
        step={1}
        lo={nodeSizeMin}
        hi={nodeSizeMax}
        format={(v) => Math.round(v) + 'px'}
        onChange={(lo, hi) => {
          nodeSizeMin = Math.round(lo);
          nodeSizeMax = Math.round(hi);
        }}
        leftLabel="fewest links"
        rightLabel="most links"
      />

      <GraphOptionsRangeField
        title="Node fade"
        dirty={nodeFadeStart !== D.nodeFadeStart || nodeFadeFull !== D.nodeFadeFull}
        onReset={() => {
          nodeFadeStart = D.nodeFadeStart;
          nodeFadeFull = D.nodeFadeFull;
        }}
        min={nodeFadeBoundMin}
        max={nodeFadeBoundMax}
        step={0.02}
        lo={nodeFadeStart}
        hi={nodeFadeFull}
        format={(v) => v.toFixed(2)}
        onChange={(lo, hi) => {
          nodeFadeStart = Math.round(lo * 50) / 50;
          nodeFadeFull = Math.round(hi * 50) / 50;
        }}
        leftLabel="transparent"
        rightLabel="solid"
      />

      <div class={cn(nodeFadeStart === 0 && nodeFadeFull === 0 && 'pointer-events-none opacity-40')}>
        <GraphOptionsRangeField
          title="Zoom reveal"
          dirty={nodeRevealLo !== D.nodeRevealLo || nodeRevealHi !== D.nodeRevealHi}
          onReset={() => {
            nodeRevealLo = D.nodeRevealLo;
            nodeRevealHi = D.nodeRevealHi;
          }}
          min={nodeRevealZoomMin}
          max={nodeRevealZoomMax}
          step={0.1}
          lo={nodeRevealLo}
          hi={nodeRevealHi}
          format={(v) => v.toFixed(1) + '×'}
          onChange={(lo, hi) => {
            nodeRevealLo = r1(lo);
            nodeRevealHi = r1(hi);
          }}
          leftLabel="hazy (far)"
          rightLabel="clear (near)"
        />
      </div>

      <GraphOptionsScalarField
        title="Edge curvature"
        dirty={curveAmount !== D.curveAmount}
        onReset={() => (curveAmount = D.curveAmount)}
        valueText={curveAmount.toFixed(2)}
        min={0}
        max={1}
        step={0.05}
        value={curveAmount}
        onInput={(v) => (curveAmount = v)}
        leftLabel="straight"
        rightLabel="curved"
        ariaLabel="Curvature of edges between nodes"
      />

      <GraphOptionsButtonGroup
        title="Search focus"
        dirty={searchFocusMode !== D.searchFocusMode}
        onReset={() => (searchFocusMode = D.searchFocusMode)}
        modes={FOCUS_MODES}
        value={searchFocusMode}
        onChange={(v) => (searchFocusMode = v as SearchFocusMode)}
        ariaLabel="How search treats non-matching nodes and edges"
      />

      <GraphOptionsButtonGroup
        title="Selection focus"
        dirty={selectionFocusMode !== D.selectionFocusMode}
        onReset={() => (selectionFocusMode = D.selectionFocusMode)}
        modes={SELECTION_MODES}
        value={selectionFocusMode}
        onChange={(v) => (selectionFocusMode = v as SelectionFocusMode)}
        ariaLabel="How a selected node focuses its neighborhood"
      />

      <GraphOptionsRangeField
        title="Edge label — visible zoom"
        dirty={edgeZoomMin !== D.edgeZoomMin || edgeZoomMax !== D.edgeZoomMax}
        onReset={() => {
          edgeZoomMin = D.edgeZoomMin;
          edgeZoomMax = D.edgeZoomMax;
        }}
        min={zoomBoundMin}
        max={zoomBoundMax}
        step={0.1}
        lo={edgeZoomMin}
        hi={edgeZoomMax}
        format={(v) => v.toFixed(1) + '×'}
        onChange={(lo, hi) => {
          edgeZoomMin = r1(lo);
          edgeZoomMax = r1(hi);
        }}
      />

      <GraphOptionsRangeField
        title="Edge label — font size"
        dirty={edgeFontMin !== D.edgeFontMin || edgeFontMax !== D.edgeFontMax}
        onReset={() => {
          edgeFontMin = D.edgeFontMin;
          edgeFontMax = D.edgeFontMax;
        }}
        min={fontBoundMin}
        max={fontBoundMax}
        step={1}
        lo={edgeFontMin}
        hi={edgeFontMax}
        format={(v) => Math.round(v) + 'px'}
        onChange={(lo, hi) => {
          edgeFontMin = Math.round(lo);
          edgeFontMax = Math.round(hi);
        }}
      />

      <GraphOptionsRangeField
        title="Node label — visible zoom"
        dirty={nodeZoomMin !== D.nodeZoomMin || nodeZoomMax !== D.nodeZoomMax}
        onReset={() => {
          nodeZoomMin = D.nodeZoomMin;
          nodeZoomMax = D.nodeZoomMax;
        }}
        min={zoomBoundMin}
        max={zoomBoundMax}
        step={0.1}
        lo={nodeZoomMin}
        hi={nodeZoomMax}
        format={(v) => v.toFixed(1) + '×'}
        onChange={(lo, hi) => {
          nodeZoomMin = r1(lo);
          nodeZoomMax = r1(hi);
        }}
      />

      <GraphOptionsRangeField
        title="Node label — font size"
        dirty={nodeFontMin !== D.nodeFontMin || nodeFontMax !== D.nodeFontMax}
        onReset={() => {
          nodeFontMin = D.nodeFontMin;
          nodeFontMax = D.nodeFontMax;
        }}
        min={fontBoundMin}
        max={fontBoundMax}
        step={1}
        lo={nodeFontMin}
        hi={nodeFontMax}
        format={(v) => Math.round(v) + 'px'}
        onChange={(lo, hi) => {
          nodeFontMin = Math.round(lo);
          nodeFontMax = Math.round(hi);
        }}
      />

      <GraphOptionsScalarField
        title="Edge label max length"
        dirty={edgeLabelMax !== D.edgeLabelMax}
        onReset={() => (edgeLabelMax = D.edgeLabelMax)}
        valueText={String(edgeLabelMax)}
        min={edgeLabelMaxMin}
        max={edgeLabelMaxMax}
        step={1}
        value={edgeLabelMax}
        onInput={(v) => (edgeLabelMax = v)}
        leftLabel="short"
        rightLabel="long"
        ariaLabel="Trim edge labels longer than this many characters"
      />
    </div>
  {/if}
</section>
