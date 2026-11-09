<script lang="ts">
  // Logs → AI usage (Phase 7b): totals per value of what the page groups by (each use, model,
  // label…). Picking a row keeps only it and groups by the next useful dimension.
  import { colorOf, DIMENSIONS, OTHER, short, usd, type Dimension, type Group } from './ai-usage';

  let {
    groups,
    groupBy,
    keys,
    onpick
  }: { groups: Group[]; groupBy: Dimension; keys: string[]; onpick: (key: string) => void } = $props();

  const all = $derived(groups.reduce((n, g) => n + g.requests, 0));
  const title = $derived(DIMENSIONS.find((d) => d.value === groupBy)?.label ?? '');
  const color = (k: string) => (keys.includes(k) ? colorOf(keys, k) : colorOf(keys, OTHER));
  const cols =
    'grid grid-cols-[minmax(0,1.6fr)_minmax(7rem,1fr)_repeat(5,minmax(4.5rem,0.5fr))] items-center gap-3';
</script>

<div class="grid min-w-0 overflow-x-auto rounded-md border bg-card p-3 font-sans text-sm shadow-sm">
  <div class="{cols} min-w-[48rem] border-b pb-1.5 text-xs uppercase text-muted-foreground">
    <span>{title}</span><span>Calls</span>
    <span class="text-right" title="Tokens sent per call, on average">Tokens in each</span>
    <span class="text-right">Avg time</span><span class="text-right">Failed</span>
    <span class="text-right">Billed</span><span class="text-right" title="What the plans' calls would cost on an API key"
      >At API prices</span
    >
  </div>
  {#each groups as g (g.key)}
    <button
      type="button"
      class="{cols} min-w-[48rem] border-b py-1.5 text-left last:border-b-0 hover:bg-muted/50"
      onclick={() => onpick(g.key)}
      title="Show only {g.key}"
    >
      <span class="flex min-w-0 items-center gap-2"
        ><span class="size-2.5 shrink-0 rounded-sm" style="background:{color(g.key)}"></span><span class="truncate"
          >{g.key}</span
        ></span
      >
      <span class="flex items-center gap-2 tabular-nums"
        ><span class="w-12 text-right">{short(g.requests)}</span><span class="h-1.5 flex-1 rounded-full bg-muted"
          ><span class="block h-full rounded-full bg-primary/70" style="width:{all ? (g.requests / all) * 100 : 0}%"></span></span
        ></span
      >
      <span class="text-right tabular-nums">{g.tokensIn ? short(g.tokensIn / g.requests) : '–'}</span>
      <span class="text-right tabular-nums">{(g.ms / g.requests / 1000).toFixed(1)} s</span>
      <span class="text-right tabular-nums {g.failed ? 'text-destructive' : 'text-muted-foreground'}"
        >{g.failed ? `${((g.failed / g.requests) * 100).toFixed(1)}%` : '–'}</span
      >
      <span class="text-right tabular-nums">{g.billed ? usd(g.billed) : g.unpriced && g.plan < g.requests ? 'no price' : '–'}</span>
      <span class="text-right tabular-nums">{g.plan ? (g.estimate ? usd(g.estimate) : 'no price') : '–'}</span>
    </button>
  {:else}
    <p class="py-3 text-sm text-muted-foreground">No AI calls in these days with these filters.</p>
  {/each}
</div>
