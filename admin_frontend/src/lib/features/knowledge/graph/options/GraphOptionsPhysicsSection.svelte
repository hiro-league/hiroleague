<script lang="ts">
  import { ChevronDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { GRAPH_OPTION_DEFAULTS as D } from '../knowledge-graph-prefs';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    open = $bindable(true),
    linkStrength = $bindable(),
    linkDistance = $bindable(),
    centerStrength = $bindable(),
    radialRing = $bindable(),
    chargeStrength = $bindable(),
    hubSeparation = $bindable(),
    hubSpacing = $bindable(),
    collideScale = $bindable(),
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
    collideScaleMax
  }: {
    open?: boolean;
    linkStrength: number;
    linkDistance: number;
    centerStrength: number;
    radialRing: number;
    chargeStrength: number;
    hubSeparation: number;
    hubSpacing: number;
    collideScale: number;
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
  } = $props();
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
    <span>Physics</span>
    <ChevronDown size={14} class={cn('transition-transform', open || 'rotate-180')} aria-hidden="true" />
  </button>
  {#if open}
    <div class="space-y-3 p-2.5">
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Link strength
            <GraphOptionsResetDot dirty={linkStrength !== D.linkStrength} onReset={() => (linkStrength = D.linkStrength)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{linkStrength.toFixed(2)}</span>
        </div>
        <input type="range" min="0" max="1" step="0.05" bind:value={linkStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Link strength between nodes" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>loose</span><span>tight</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Link distance
            <GraphOptionsResetDot dirty={linkDistance !== D.linkDistance} onReset={() => (linkDistance = D.linkDistance)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{linkDistance}</span>
        </div>
        <input type="range" min="20" max="300" step="5" bind:value={linkDistance} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Resting distance of edges between nodes" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>near</span><span>far</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Node repulsion
            <GraphOptionsResetDot dirty={chargeStrength !== D.chargeStrength} onReset={() => (chargeStrength = D.chargeStrength)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{Math.abs(chargeStrength)}</span>
        </div>
        <input type="range" min={chargeMin} max={chargeMax} step="20" bind:value={chargeStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How strongly nodes push each other apart" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>spread</span><span>clump</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Center pull
            <GraphOptionsResetDot dirty={centerStrength !== D.centerStrength} onReset={() => (centerStrength = D.centerStrength)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{centerStrength.toFixed(2)}</span>
        </div>
        <input type="range" min="0" max={centerStrengthMax} step="0.01" bind:value={centerStrength} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How strongly all nodes are pulled toward the center" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>loose</span><span>tight</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Spread radius
            <GraphOptionsResetDot dirty={radialRing !== D.radialRing} onReset={() => (radialRing = D.radialRing)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{radialRing}</span>
        </div>
        <input type="range" min={radialRingMin} max={radialRingMax} step="5" bind:value={radialRing} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How far the least-connected and disconnected nodes sit from the center" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>tight</span><span>wide</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Hub separation
            <GraphOptionsResetDot dirty={hubSeparation !== D.hubSeparation} onReset={() => (hubSeparation = D.hubSeparation)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{hubSeparation.toFixed(2)}</span>
        </div>
        <input type="range" min={hubSeparationMin} max={hubSeparationMax} step="0.05" bind:value={hubSeparation} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How strongly high-connection hubs are pushed apart from each other" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>off</span><span>spread hubs</span></div>
      </label>
      <label class={cn('block', hubSeparation === 0 && 'pointer-events-none opacity-40')}>
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Hub spacing
            <GraphOptionsResetDot dirty={hubSpacing !== D.hubSpacing} onReset={() => (hubSpacing = D.hubSpacing)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{hubSpacing.toFixed(2)}×</span>
        </div>
        <input type="range" min={hubSpacingMin} max={hubSpacingMax} step="0.25" bind:value={hubSpacing} disabled={hubSeparation === 0} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="How far apart the separated hubs settle" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>near</span><span>far</span></div>
      </label>
      <label class="block">
        <div class="mb-1 flex items-center justify-between text-xs">
          <span class="flex items-center font-medium">
            Collision spacing
            <GraphOptionsResetDot dirty={collideScale !== D.collideScale} onReset={() => (collideScale = D.collideScale)} />
          </span>
          <span class="tabular-nums text-muted-foreground">{collideScale.toFixed(2)}×</span>
        </div>
        <input type="range" min={collideScaleMin} max={collideScaleMax} step="0.05" bind:value={collideScale} class="h-1.5 w-full cursor-pointer accent-primary" aria-label="Collision radius multiplier — extra spacing so labels don't cover other nodes" />
        <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground"><span>normal</span><span>roomy</span></div>
      </label>
    </div>
  {/if}
</section>
