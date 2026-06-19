<script lang="ts">
  import { ChevronDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import GraphRangeSlider from '../GraphRangeSlider.svelte';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';
  import {
    LOW_CONN_THRESHOLD_MIN,
    MAX_CONN_PER_NODE_CAP,
    VISIBLE_EDGES_CAP,
    VISIBLE_EDGES_MIN,
    type EdgeValidity,
    type KnowledgeGraphModel,
    type LowConnTreatment,
    type MaxConnBy
  } from '../../state/knowledge-graph.svelte';

  let {
    graph,
    open = $bindable(true)
  }: {
    graph: KnowledgeGraphModel;
    open?: boolean;
  } = $props();

  const VALIDITY_MODES: { value: EdgeValidity; label: string; title: string }[] = [
    { value: 'all', label: 'All', title: 'Show every edge' },
    { value: 'valid', label: 'Valid', title: 'Only current facts (not invalidated or expired)' },
    { value: 'invalid', label: 'Invalid', title: 'Only superseded facts (invalid_at or expired_at set)' }
  ];
  const LOW_CONN_TREATMENTS: { value: LowConnTreatment; label: string; title: string }[] = [
    { value: 'dim', label: 'Dim', title: 'Fade sparse nodes (layout unchanged)' },
    { value: 'hide', label: 'Hide', title: 'Remove sparse nodes from the graph' }
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
  const maxConnUnlimited = $derived(graph.maxConnPerNode() >= MAX_CONN_PER_NODE_CAP);
  const visibleEdgesUnlimited = $derived(graph.visibleEdgesPerPair() >= VISIBLE_EDGES_CAP);
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
    <span>Filters</span>
    <ChevronDown size={14} class={cn('transition-transform', open || 'rotate-180')} aria-hidden="true" />
  </button>
  {#if open}
    <div class="space-y-3 p-2.5">
      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Edge validation
            <GraphOptionsResetDot
              dirty={graph.edgeValidity() !== 'all'}
              onReset={() => graph.setEdgeValidity('all')}
            />
          </span>
        </div>
        <div class="grid grid-cols-3 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Filter edges by validity">
          {#each VALIDITY_MODES as mode (mode.value)}
            {@const active = graph.edgeValidity() === mode.value}
            <button
              type="button"
              onclick={() => graph.setEdgeValidity(mode.value)}
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
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Denoise sparse nodes
            <GraphOptionsResetDot
              dirty={graph.lowConnThreshold() > 0}
              onReset={() => graph.setLowConnThreshold(0)}
            />
          </span>
          <div class="grid grid-cols-2 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="How to treat sparse nodes">
            {#each LOW_CONN_TREATMENTS as t (t.value)}
              {@const active = graph.lowConnTreatment() === t.value}
              <button
                type="button"
                onclick={() => graph.setLowConnTreatment(t.value)}
                class={cn(
                  'rounded px-2 py-0.5 text-xs font-medium transition-colors',
                  active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
                )}
                aria-pressed={active}
                title={t.title}
              >
                {t.label}
              </button>
            {/each}
          </div>
        </div>
        <div class="flex items-center gap-1.5 text-xs">
          <span class="text-muted-foreground">Fewer than</span>
          <input
            type="number"
            min={LOW_CONN_THRESHOLD_MIN}
            max={Math.max(1, graph.maxVisibleDegree())}
            step="1"
            value={graph.lowConnThreshold()}
            oninput={(e) => graph.setLowConnThreshold(e.currentTarget.valueAsNumber || 0)}
            class="h-7 w-14 rounded-md border border-input bg-background px-2 text-xs tabular-nums outline-hidden focus:border-primary"
            aria-label="Connection count below which a node is dimmed or hidden (0 = off)"
          />
          <span class="text-muted-foreground">
            conn{graph.lowConnThreshold() > 0 ? ` · ${graph.lowConnCount()} nodes` : ' (0 = off)'}
          </span>
        </div>
      </div>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Valid date
            <GraphOptionsResetDot
              dirty={graph.validRange() !== null}
              onReset={() => validSpan && graph.setValidRange({ lo: validSpan.lo, hi: validSpan.hi })}
            />
          </span>
        </div>
        {#if validSpan}
          <GraphRangeSlider
            min={validSpan.lo}
            max={validSpan.hi}
            step={rangeStep(validSpan)}
            value={validValue}
            format={fmtDate}
            onChange={(lo, hi) => graph.setValidRange({ lo, hi })}
          />
        {:else}
          <p class="text-[10px] text-muted-foreground">No facts carry a valid date.</p>
        {/if}
      </div>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Creation date
            <GraphOptionsResetDot
              dirty={graph.creationRange() !== null}
              onReset={() => creationSpan && graph.setCreationRange({ lo: creationSpan.lo, hi: creationSpan.hi })}
            />
          </span>
        </div>
        {#if creationSpan}
          <GraphRangeSlider
            min={creationSpan.lo}
            max={creationSpan.hi}
            step={rangeStep(creationSpan)}
            value={creationValue}
            format={fmtDate}
            onChange={(lo, hi) => graph.setCreationRange({ lo, hi })}
          />
        {:else}
          <p class="text-[10px] text-muted-foreground">No facts carry a creation date.</p>
        {/if}
      </div>

      <label class="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={graph.includeUndatedEdges()}
          onchange={(e) => graph.setIncludeUndatedEdges(e.currentTarget.checked)}
          class="size-3.5 cursor-pointer accent-primary"
        />
        <span class="flex items-center font-medium">
          Include edges without a date
          <GraphOptionsResetDot
            dirty={!graph.includeUndatedEdges()}
            onReset={() => graph.setIncludeUndatedEdges(true)}
          />
        </span>
      </label>

      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Max connections per node
            <GraphOptionsResetDot
              dirty={!maxConnUnlimited}
              onReset={() => graph.setMaxConnPerNode(MAX_CONN_PER_NODE_CAP)}
            />
          </span>
          <span class="tabular-nums text-muted-foreground">{maxConnUnlimited ? 'All' : graph.maxConnPerNode()}</span>
        </div>
        <input
          type="range"
          min="1"
          max={MAX_CONN_PER_NODE_CAP}
          step="1"
          value={graph.maxConnPerNode()}
          oninput={(e) => graph.setMaxConnPerNode(e.currentTarget.valueAsNumber)}
          class="h-1.5 w-full cursor-pointer accent-primary"
          aria-label="Maximum number of connections shown per node"
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>1</span><span>all</span></div>
      </label>

      <div>
        <div class="mb-1 flex items-center text-xs">
          <span class="flex items-center font-medium">
            Keep which connections
            <GraphOptionsResetDot dirty={graph.maxConnBy() !== 'newest'} onReset={() => graph.setMaxConnBy('newest')} />
          </span>
        </div>
        <div class="grid grid-cols-2 gap-0.5 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Which connections to keep when capping">
          {#each MAX_BY_MODES as mode (mode.value)}
            {@const active = graph.maxConnBy() === mode.value}
            <button
              type="button"
              onclick={() => graph.setMaxConnBy(mode.value)}
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

      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Max visible edges between nodes
            <GraphOptionsResetDot
              dirty={!visibleEdgesUnlimited}
              onReset={() => graph.setVisibleEdgesPerPair(VISIBLE_EDGES_CAP)}
            />
          </span>
          <span class="tabular-nums text-muted-foreground">{visibleEdgesUnlimited ? 'All' : graph.visibleEdgesPerPair()}</span>
        </div>
        <input
          type="range"
          min={VISIBLE_EDGES_MIN}
          max={VISIBLE_EDGES_CAP}
          step="1"
          value={graph.visibleEdgesPerPair()}
          oninput={(e) => graph.setVisibleEdgesPerPair(e.currentTarget.valueAsNumber)}
          class="h-1.5 w-full cursor-pointer accent-primary"
          aria-label="Maximum edges shown per entity pair before the rest collapse into one aggregate edge"
        />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>{VISIBLE_EDGES_MIN}</span><span>all</span></div>
      </label>
    </div>
  {/if}
</section>
