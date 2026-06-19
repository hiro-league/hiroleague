<script lang="ts">
  import { ChevronDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { GRAPH_OPTION_DEFAULTS as D, type SearchFocusMode, type SelectionFocusMode } from '../knowledge-graph-prefs';
  import GraphRangeSlider from '../GraphRangeSlider.svelte';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

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
      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Node size
            <GraphOptionsResetDot
              dirty={nodeSizeMin !== D.nodeSizeMin || nodeSizeMax !== D.nodeSizeMax}
              onReset={() => {
                nodeSizeMin = D.nodeSizeMin;
                nodeSizeMax = D.nodeSizeMax;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={nodeSizeBoundMin}
          max={nodeSizeBoundMax}
          step={1}
          value={[nodeSizeMin, nodeSizeMax]}
          format={(v) => Math.round(v) + 'px'}
          onChange={(lo, hi) => {
            nodeSizeMin = Math.round(lo);
            nodeSizeMax = Math.round(hi);
          }}
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>fewest links</span><span>most links</span></div>
      </div>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Node fade
            <GraphOptionsResetDot
              dirty={nodeFadeStart !== D.nodeFadeStart || nodeFadeFull !== D.nodeFadeFull}
              onReset={() => {
                nodeFadeStart = D.nodeFadeStart;
                nodeFadeFull = D.nodeFadeFull;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={nodeFadeBoundMin}
          max={nodeFadeBoundMax}
          step={0.02}
          value={[nodeFadeStart, nodeFadeFull]}
          format={(v) => v.toFixed(2)}
          onChange={(lo, hi) => {
            nodeFadeStart = Math.round(lo * 50) / 50;
            nodeFadeFull = Math.round(hi * 50) / 50;
          }}
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>transparent</span><span>solid</span></div>
      </div>

      <div class={cn(nodeFadeStart === 0 && nodeFadeFull === 0 && 'pointer-events-none opacity-40')}>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Zoom reveal
            <GraphOptionsResetDot
              dirty={nodeRevealLo !== D.nodeRevealLo || nodeRevealHi !== D.nodeRevealHi}
              onReset={() => {
                nodeRevealLo = D.nodeRevealLo;
                nodeRevealHi = D.nodeRevealHi;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={nodeRevealZoomMin}
          max={nodeRevealZoomMax}
          step={0.1}
          value={[nodeRevealLo, nodeRevealHi]}
          format={(v) => v.toFixed(1) + '×'}
          onChange={(lo, hi) => {
            nodeRevealLo = r1(lo);
            nodeRevealHi = r1(hi);
          }}
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>hazy (far)</span><span>clear (near)</span></div>
      </div>

      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Edge curvature
            <GraphOptionsResetDot dirty={curveAmount !== D.curveAmount} onReset={() => (curveAmount = D.curveAmount)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{curveAmount.toFixed(2)}</span>
        </div>
        <input type="range" min="0" max="1" step="0.05" bind:value={curveAmount} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Curvature of edges between nodes" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>straight</span><span>curved</span></div>
      </label>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Search focus
            <GraphOptionsResetDot
              dirty={searchFocusMode !== D.searchFocusMode}
              onReset={() => (searchFocusMode = D.searchFocusMode)}
            />
          </span>
        </div>
        <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="How search treats non-matching nodes and edges">
          {#each FOCUS_MODES as mode (mode.value)}
            {@const active = searchFocusMode === mode.value}
            <button
              type="button"
              onclick={() => (searchFocusMode = mode.value)}
              class={cn(
                'rounded px-1.5 py-1 text-xs font-medium transition-colors',
                active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
              aria-pressed={active}
              title={mode.title}
            >
              {mode.label}
            </button>
          {/each}
        </div>
      </div>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Selection focus
            <GraphOptionsResetDot
              dirty={selectionFocusMode !== D.selectionFocusMode}
              onReset={() => (selectionFocusMode = D.selectionFocusMode)}
            />
          </span>
        </div>
        <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="How a selected node focuses its neighborhood">
          {#each SELECTION_MODES as mode (mode.value)}
            {@const active = selectionFocusMode === mode.value}
            <button
              type="button"
              onclick={() => (selectionFocusMode = mode.value)}
              class={cn(
                'rounded px-1.5 py-1 text-xs font-medium transition-colors',
                active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
              aria-pressed={active}
              title={mode.title}
            >
              {mode.label}
            </button>
          {/each}
        </div>
      </div>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Edge label — visible zoom
            <GraphOptionsResetDot
              dirty={edgeZoomMin !== D.edgeZoomMin || edgeZoomMax !== D.edgeZoomMax}
              onReset={() => {
                edgeZoomMin = D.edgeZoomMin;
                edgeZoomMax = D.edgeZoomMax;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={zoomBoundMin}
          max={zoomBoundMax}
          step={0.1}
          value={[edgeZoomMin, edgeZoomMax]}
          format={(v) => v.toFixed(1) + '×'}
          onChange={(lo, hi) => {
            edgeZoomMin = r1(lo);
            edgeZoomMax = r1(hi);
          }}
        />
      </div>
      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Edge label — font size
            <GraphOptionsResetDot
              dirty={edgeFontMin !== D.edgeFontMin || edgeFontMax !== D.edgeFontMax}
              onReset={() => {
                edgeFontMin = D.edgeFontMin;
                edgeFontMax = D.edgeFontMax;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={fontBoundMin}
          max={fontBoundMax}
          step={1}
          value={[edgeFontMin, edgeFontMax]}
          format={(v) => Math.round(v) + 'px'}
          onChange={(lo, hi) => {
            edgeFontMin = Math.round(lo);
            edgeFontMax = Math.round(hi);
          }}
        />
      </div>
      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Node label — visible zoom
            <GraphOptionsResetDot
              dirty={nodeZoomMin !== D.nodeZoomMin || nodeZoomMax !== D.nodeZoomMax}
              onReset={() => {
                nodeZoomMin = D.nodeZoomMin;
                nodeZoomMax = D.nodeZoomMax;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={zoomBoundMin}
          max={zoomBoundMax}
          step={0.1}
          value={[nodeZoomMin, nodeZoomMax]}
          format={(v) => v.toFixed(1) + '×'}
          onChange={(lo, hi) => {
            nodeZoomMin = r1(lo);
            nodeZoomMax = r1(hi);
          }}
        />
      </div>
      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Node label — font size
            <GraphOptionsResetDot
              dirty={nodeFontMin !== D.nodeFontMin || nodeFontMax !== D.nodeFontMax}
              onReset={() => {
                nodeFontMin = D.nodeFontMin;
                nodeFontMax = D.nodeFontMax;
              }}
            />
          </span>
        </div>
        <GraphRangeSlider
          min={fontBoundMin}
          max={fontBoundMax}
          step={1}
          value={[nodeFontMin, nodeFontMax]}
          format={(v) => Math.round(v) + 'px'}
          onChange={(lo, hi) => {
            nodeFontMin = Math.round(lo);
            nodeFontMax = Math.round(hi);
          }}
        />
      </div>

      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Edge label max length
            <GraphOptionsResetDot dirty={edgeLabelMax !== D.edgeLabelMax} onReset={() => (edgeLabelMax = D.edgeLabelMax)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{edgeLabelMax}</span>
        </div>
        <input
          type="range"
          min={edgeLabelMaxMin}
          max={edgeLabelMaxMax}
          step="1"
          bind:value={edgeLabelMax}
          class="h-1.5 w-full cursor-pointer accent-primary"
          aria-label="Trim edge labels longer than this many characters"
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>short</span><span>long</span></div>
      </label>
    </div>
  {/if}
</section>
