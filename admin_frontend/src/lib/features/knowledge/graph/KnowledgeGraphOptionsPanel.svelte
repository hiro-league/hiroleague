<script lang="ts">
  /**
   * Left-side "Graph options" panel. Three collapsible sections (Filters → View → Physics):
   *  • Filters — edge/node visibility (validity / dates / orphans / connection caps), model-backed.
   *  • View — visual treatment that doesn't change membership (curvature, focus modes, label sizing).
   *  • Physics — live layout forces (parent owns the values, applies them to force-graph).
   * Each control carries a subtle reset (↺) shown only when it differs from its default; a global
   * Reset lives in the header. Toggled by a button in the graph's upper-left corner.
   */
  import { ChevronDown, RotateCcw, X } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { GRAPH_OPTION_DEFAULTS as D, type SearchFocusMode, type SelectionFocusMode } from './knowledge-graph-prefs';
  import GraphRangeSlider from './GraphRangeSlider.svelte';
  import {
    MAX_CONN_PER_NODE_CAP,
    type EdgeValidity,
    type KnowledgeGraphModel,
    type MaxConnBy,
    type OrphanMode
  } from '../state/knowledge-graph.svelte';

  let {
    graph,
    linkStrength = $bindable(),
    linkDistance = $bindable(),
    centerStrength = $bindable(),
    radialRing = $bindable(),
    curveAmount = $bindable(),
    maxLinksPerPair = $bindable(),
    chargeStrength = $bindable(),
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
    maxLinksCap,
    chargeMin,
    chargeMax,
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
    maxLinksPerPair: number;
    chargeStrength: number;
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
    maxLinksCap: number;
    chargeMin: number;
    chargeMax: number;
    zoomBoundMin: number;
    zoomBoundMax: number;
    fontBoundMin: number;
    fontBoundMax: number;
    edgeLabelMaxMin: number;
    edgeLabelMaxMax: number;
    onReset: () => void;
    onClose: () => void;
  } = $props();

  let filtersOpen = $state(true);
  let viewOpen = $state(true);
  let physicsOpen = $state(true);

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
  const VALIDITY_MODES: { value: EdgeValidity; label: string; title: string }[] = [
    { value: 'all', label: 'All', title: 'Show every edge' },
    { value: 'valid', label: 'Valid', title: 'Only current facts (not invalidated or expired)' },
    { value: 'invalid', label: 'Invalid', title: 'Only superseded facts (invalid_at or expired_at set)' }
  ];
  const ORPHAN_MODES: { value: OrphanMode; label: string; title: string }[] = [
    { value: 'all', label: 'All', title: 'Show every node' },
    { value: 'hide', label: 'Hide', title: 'Hide nodes with no visible connections' },
    { value: 'only', label: 'Only', title: 'Show only nodes with no visible connections' }
  ];
  const MAX_BY_MODES: { value: MaxConnBy; label: string; title: string }[] = [
    { value: 'newest', label: 'Newest', title: 'Keep the most recent edges (by valid date)' },
    { value: 'oldest', label: 'Oldest', title: 'Keep the oldest edges (by valid date)' }
  ];

  const validSpan = $derived(graph.validAtSpan());
  const creationSpan = $derived(graph.createdAtSpan());
  const validValue = $derived.by<[number, number]>(() => {
    const s = graph.validAtSpan();
    const r = graph.validRange();
    if (!s) return [0, 0];
    return r ? [r.lo, r.hi] : [s.lo, s.hi];
  });
  const creationValue = $derived.by<[number, number]>(() => {
    const s = graph.createdAtSpan();
    const r = graph.creationRange();
    if (!s) return [0, 0];
    return r ? [r.lo, r.hi] : [s.lo, s.hi];
  });
  const rangeStep = (s: { lo: number; hi: number } | null): number =>
    s ? Math.max(1, Math.round((s.hi - s.lo) / 100)) : 1;
  const fmtDate = (v: number): string =>
    new Date(v).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  const r1 = (v: number): number => Math.round(v * 10) / 10;
  const maxConnUnlimited = $derived(graph.maxConnPerNode() >= MAX_CONN_PER_NODE_CAP);
</script>

{#snippet resetDot(dirty: boolean, reset: () => void)}
  {#if dirty}
    <button
      type="button"
      onclick={reset}
      title="Reset to default"
      aria-label="Reset to default"
      class="ml-1 inline-flex size-3.5 shrink-0 items-center justify-center rounded text-muted-foreground/60 hover:bg-muted hover:text-foreground"
    >
      <RotateCcw size={10} aria-hidden="true" />
    </button>
  {/if}
{/snippet}

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

  <!-- scrollbar-gutter:stable always reserves the scrollbar track so sections don't shrink/jump
       when the bar appears; scrollbar-width:thin keeps that reserved gutter narrow. -->
  <div class="min-h-0 flex-1 space-y-3 overflow-y-auto p-2.5 [scrollbar-gutter:stable] [scrollbar-width:thin]">
    <!-- ── Filters ─────────────────────────────────────────────────────────── -->
    <section class="overflow-hidden rounded-lg border border-primary/40">
      <button type="button" onclick={() => (filtersOpen = !filtersOpen)} aria-expanded={filtersOpen} class={cn('flex w-full items-center justify-between bg-primary/20 px-2.5 py-1.5 text-xs font-semibold text-foreground', filtersOpen && 'border-b border-primary/40')}>
        <span>Filters</span>
        <ChevronDown size={14} class={cn('transition-transform', filtersOpen || 'rotate-180')} aria-hidden="true" />
      </button>
      {#if filtersOpen}
        <div class="space-y-3 p-2.5">
          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Edge validation{@render resetDot(graph.edgeValidity() !== 'all', () => graph.setEdgeValidity('all'))}</span></div>
            <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Filter edges by validity">
              {#each VALIDITY_MODES as mode (mode.value)}
                {@const active = graph.edgeValidity() === mode.value}
                <button type="button" onclick={() => graph.setEdgeValidity(mode.value)} class={cn('rounded px-1.5 py-1 text-xs font-medium transition-colors', active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')} aria-pressed={active} title={mode.title}>{mode.label}</button>
              {/each}
            </div>
          </div>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Orphan nodes{@render resetDot(graph.orphanMode() !== 'all', () => graph.setOrphanMode('all'))}</span></div>
            <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Filter nodes with no visible connections">
              {#each ORPHAN_MODES as mode (mode.value)}
                {@const active = graph.orphanMode() === mode.value}
                <button type="button" onclick={() => graph.setOrphanMode(mode.value)} class={cn('rounded px-1.5 py-1 text-xs font-medium transition-colors', active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')} aria-pressed={active} title={mode.title}>{mode.label}</button>
              {/each}
            </div>
          </div>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Valid date{@render resetDot(graph.validRange() !== null, () => validSpan && graph.setValidRange({ lo: validSpan.lo, hi: validSpan.hi }))}</span></div>
            {#if validSpan}
              <GraphRangeSlider min={validSpan.lo} max={validSpan.hi} step={rangeStep(validSpan)} value={validValue} format={fmtDate} onChange={(lo, hi) => graph.setValidRange({ lo, hi })} />
            {:else}
              <p class="text-[10px] text-muted-foreground">No facts carry a valid date.</p>
            {/if}
          </div>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Creation date{@render resetDot(graph.creationRange() !== null, () => creationSpan && graph.setCreationRange({ lo: creationSpan.lo, hi: creationSpan.hi }))}</span></div>
            {#if creationSpan}
              <GraphRangeSlider min={creationSpan.lo} max={creationSpan.hi} step={rangeStep(creationSpan)} value={creationValue} format={fmtDate} onChange={(lo, hi) => graph.setCreationRange({ lo, hi })} />
            {:else}
              <p class="text-[10px] text-muted-foreground">No facts carry a creation date.</p>
            {/if}
          </div>

          <label class="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={graph.includeUndatedEdges()} onchange={(e) => graph.setIncludeUndatedEdges(e.currentTarget.checked)} class="size-3.5 cursor-pointer accent-primary" />
            <span class="flex items-center font-medium">Include edges without a date{@render resetDot(!graph.includeUndatedEdges(), () => graph.setIncludeUndatedEdges(true))}</span>
          </label>

          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Max connections per node{@render resetDot(!maxConnUnlimited, () => graph.setMaxConnPerNode(MAX_CONN_PER_NODE_CAP))}</span><span class="tabular-nums text-muted-foreground">{maxConnUnlimited ? 'All' : graph.maxConnPerNode()}</span></div>
            <input type="range" min="1" max={MAX_CONN_PER_NODE_CAP} step="1" value={graph.maxConnPerNode()} oninput={(e) => graph.setMaxConnPerNode(e.currentTarget.valueAsNumber)} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Maximum number of connections shown per node" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>1</span><span>all</span></div>
          </label>

          {#if !maxConnUnlimited}
            <div>
              <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Keep which connections{@render resetDot(graph.maxConnBy() !== 'newest', () => graph.setMaxConnBy('newest'))}</span></div>
              <div class="grid grid-cols-2 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Which connections to keep when capping">
                {#each MAX_BY_MODES as mode (mode.value)}
                  {@const active = graph.maxConnBy() === mode.value}
                  <button type="button" onclick={() => graph.setMaxConnBy(mode.value)} class={cn('rounded px-1.5 py-1 text-xs font-medium transition-colors', active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')} aria-pressed={active} title={mode.title}>{mode.label}</button>
                {/each}
              </div>
            </div>
          {/if}

          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Max links per pair{@render resetDot(maxLinksPerPair !== D.maxLinksPerPair, () => (maxLinksPerPair = D.maxLinksPerPair))}</span><span class="tabular-nums text-muted-foreground">{maxLinksPerPair >= maxLinksCap ? 'All' : maxLinksPerPair}</span></div>
            <input type="range" min="1" max={maxLinksCap} step="1" bind:value={maxLinksPerPair} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Maximum number of edges shown between any two nodes" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>1</span><span>all</span></div>
          </label>
        </div>
      {/if}
    </section>

    <!-- ── View ────────────────────────────────────────────────────────────── -->
    <section class="overflow-hidden rounded-lg border border-primary/40">
      <button type="button" onclick={() => (viewOpen = !viewOpen)} aria-expanded={viewOpen} class={cn('flex w-full items-center justify-between bg-primary/20 px-2.5 py-1.5 text-xs font-semibold text-foreground', viewOpen && 'border-b border-primary/40')}>
        <span>View</span>
        <ChevronDown size={14} class={cn('transition-transform', viewOpen || 'rotate-180')} aria-hidden="true" />
      </button>
      {#if viewOpen}
        <div class="space-y-3 p-2.5">
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Edge curvature{@render resetDot(curveAmount !== D.curveAmount, () => (curveAmount = D.curveAmount))}</span><span class="tabular-nums text-muted-foreground">{curveAmount.toFixed(2)}</span></div>
            <input type="range" min="0" max="1" step="0.05" bind:value={curveAmount} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Curvature of edges between nodes" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>straight</span><span>curved</span></div>
          </label>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Search focus{@render resetDot(searchFocusMode !== D.searchFocusMode, () => (searchFocusMode = D.searchFocusMode))}</span></div>
            <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="How search treats non-matching nodes and edges">
              {#each FOCUS_MODES as mode (mode.value)}
                {@const active = searchFocusMode === mode.value}
                <button type="button" onclick={() => (searchFocusMode = mode.value)} class={cn('rounded px-1.5 py-1 text-xs font-medium transition-colors', active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')} aria-pressed={active} title={mode.title}>{mode.label}</button>
              {/each}
            </div>
          </div>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Selection focus{@render resetDot(selectionFocusMode !== D.selectionFocusMode, () => (selectionFocusMode = D.selectionFocusMode))}</span></div>
            <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="How a selected node focuses its neighborhood">
              {#each SELECTION_MODES as mode (mode.value)}
                {@const active = selectionFocusMode === mode.value}
                <button type="button" onclick={() => (selectionFocusMode = mode.value)} class={cn('rounded px-1.5 py-1 text-xs font-medium transition-colors', active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')} aria-pressed={active} title={mode.title}>{mode.label}</button>
              {/each}
            </div>
          </div>

          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Edge label — visible zoom{@render resetDot(edgeZoomMin !== D.edgeZoomMin || edgeZoomMax !== D.edgeZoomMax, () => { edgeZoomMin = D.edgeZoomMin; edgeZoomMax = D.edgeZoomMax; })}</span></div>
            <GraphRangeSlider min={zoomBoundMin} max={zoomBoundMax} step={0.1} value={[edgeZoomMin, edgeZoomMax]} format={(v) => v.toFixed(1) + '×'} onChange={(lo, hi) => { edgeZoomMin = r1(lo); edgeZoomMax = r1(hi); }} />
          </div>
          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Edge label — font size{@render resetDot(edgeFontMin !== D.edgeFontMin || edgeFontMax !== D.edgeFontMax, () => { edgeFontMin = D.edgeFontMin; edgeFontMax = D.edgeFontMax; })}</span></div>
            <GraphRangeSlider min={fontBoundMin} max={fontBoundMax} step={1} value={[edgeFontMin, edgeFontMax]} format={(v) => Math.round(v) + 'px'} onChange={(lo, hi) => { edgeFontMin = Math.round(lo); edgeFontMax = Math.round(hi); }} />
          </div>
          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Node label — visible zoom{@render resetDot(nodeZoomMin !== D.nodeZoomMin || nodeZoomMax !== D.nodeZoomMax, () => { nodeZoomMin = D.nodeZoomMin; nodeZoomMax = D.nodeZoomMax; })}</span></div>
            <GraphRangeSlider min={zoomBoundMin} max={zoomBoundMax} step={0.1} value={[nodeZoomMin, nodeZoomMax]} format={(v) => v.toFixed(1) + '×'} onChange={(lo, hi) => { nodeZoomMin = r1(lo); nodeZoomMax = r1(hi); }} />
          </div>
          <div>
            <div class="mb-1 flex items-center text-xs"><span class="flex items-center font-medium">Node label — font size{@render resetDot(nodeFontMin !== D.nodeFontMin || nodeFontMax !== D.nodeFontMax, () => { nodeFontMin = D.nodeFontMin; nodeFontMax = D.nodeFontMax; })}</span></div>
            <GraphRangeSlider min={fontBoundMin} max={fontBoundMax} step={1} value={[nodeFontMin, nodeFontMax]} format={(v) => Math.round(v) + 'px'} onChange={(lo, hi) => { nodeFontMin = Math.round(lo); nodeFontMax = Math.round(hi); }} />
          </div>

          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Edge label max length{@render resetDot(edgeLabelMax !== D.edgeLabelMax, () => (edgeLabelMax = D.edgeLabelMax))}</span><span class="tabular-nums text-muted-foreground">{edgeLabelMax}</span></div>
            <input type="range" min={edgeLabelMaxMin} max={edgeLabelMaxMax} step="1" bind:value={edgeLabelMax} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Trim edge labels longer than this many characters" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>short</span><span>long</span></div>
          </label>
        </div>
      {/if}
    </section>

    <!-- ── Physics ─────────────────────────────────────────────────────────── -->
    <section class="overflow-hidden rounded-lg border border-primary/40">
      <button type="button" onclick={() => (physicsOpen = !physicsOpen)} aria-expanded={physicsOpen} class={cn('flex w-full items-center justify-between bg-primary/20 px-2.5 py-1.5 text-xs font-semibold text-foreground', physicsOpen && 'border-b border-primary/40')}>
        <span>Physics</span>
        <ChevronDown size={14} class={cn('transition-transform', physicsOpen || 'rotate-180')} aria-hidden="true" />
      </button>
      {#if physicsOpen}
        <div class="space-y-3 p-2.5">
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Link strength{@render resetDot(linkStrength !== D.linkStrength, () => (linkStrength = D.linkStrength))}</span><span class="tabular-nums text-muted-foreground">{linkStrength.toFixed(2)}</span></div>
            <input type="range" min="0" max="1" step="0.05" bind:value={linkStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Link strength between nodes" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>loose</span><span>tight</span></div>
          </label>
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Link distance{@render resetDot(linkDistance !== D.linkDistance, () => (linkDistance = D.linkDistance))}</span><span class="tabular-nums text-muted-foreground">{linkDistance}</span></div>
            <input type="range" min="20" max="300" step="5" bind:value={linkDistance} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Resting distance of edges between nodes" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>near</span><span>far</span></div>
          </label>
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Node repulsion{@render resetDot(chargeStrength !== D.chargeStrength, () => (chargeStrength = D.chargeStrength))}</span><span class="tabular-nums text-muted-foreground">{Math.abs(chargeStrength)}</span></div>
            <input type="range" min={chargeMin} max={chargeMax} step="20" bind:value={chargeStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How strongly nodes push each other apart" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>spread</span><span>clump</span></div>
          </label>
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Center pull{@render resetDot(centerStrength !== D.centerStrength, () => (centerStrength = D.centerStrength))}</span><span class="tabular-nums text-muted-foreground">{centerStrength.toFixed(2)}</span></div>
            <input type="range" min="0" max={centerStrengthMax} step="0.01" bind:value={centerStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How strongly all nodes are pulled toward the center" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>loose</span><span>tight</span></div>
          </label>
          <label class="block">
            <div class="mb-1 flex items-center justify-between text-xs"><span class="flex items-center font-medium">Spread radius{@render resetDot(radialRing !== D.radialRing, () => (radialRing = D.radialRing))}</span><span class="tabular-nums text-muted-foreground">{radialRing}</span></div>
            <input type="range" min={radialRingMin} max={radialRingMax} step="5" bind:value={radialRing} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How far the least-connected and disconnected nodes sit from the center" />
            <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>tight</span><span>wide</span></div>
          </label>
        </div>
      {/if}
    </section>
  </div>
</div>
