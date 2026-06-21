<!--
  Turn-by-turn retrieval-agent trajectory for one memory-eval recall leg (P8).
  Clicking a search row highlights matching facts in the sibling Facts tab.
-->
<script lang="ts">
  import type { RecalledFact } from '$lib/features/eval/shared/eval-events';
  import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';
  import { trajectoryStats } from './eval-trajectory-controller.svelte';

  interface Props {
    loop: RetrievalLoop;
    facts: RecalledFact[];
    onSearchSelect: (sid: number) => void;
  }
  let { loop, facts, onSearchSelect }: Props = $props();

  const stats = $derived(trajectoryStats(loop, facts.length));
</script>

<div class="grid gap-3 text-xs">
  {#each loop.turns as turn (turn.turn)}
    <div class="flex items-baseline gap-3">
      <span class="min-w-[56px] font-mono font-medium">Turn {turn.turn}</span>
      <span class="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        {turn.sub_queries.length}
        {turn.sub_queries.length === 1 ? 'sub-query' : 'sub-queries'}
        {#if turn.sub_queries.length > 1} · decomposition{/if}
      </span>
    </div>
    {#each turn.sub_queries as c (c.sid)}
      <button
        type="button"
        class="grid grid-cols-[56px_1fr_auto_auto] items-center gap-x-3 gap-y-1 pl-4 text-left hover:bg-muted/40"
        title={`Highlight facts retrieved by S${c.sid}`}
        onclick={() => onSearchSelect(c.sid)}
      >
        <span class="font-mono text-muted-foreground">S{c.sid}</span>
        <div class="grid gap-0.5">
          <span class="text-muted-foreground italic">goal: "{c.goal}"</span>
          <span class="font-mono text-[11px] text-muted-foreground/80">
            {c.temporal} · limit {c.limit} · hops {c.hops}{#if c.show_expiry} · show_expiry{/if}
          </span>
        </div>
        <span class="font-mono text-muted-foreground">{c.returned} returned</span>
        <span class="rounded bg-success/15 px-2 py-0.5 font-mono text-success">+{c.new} new</span>
      </button>
    {/each}
  {/each}
  <div class="flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-2 text-xs">
    <span
      ><span class="text-muted-foreground">Reduce</span>
      <code class="ml-2 rounded bg-info/15 px-2 py-0.5 text-info">{stats.reduceLabel}</code></span
    >
    <span
      ><span class="text-muted-foreground">Stopped</span>
      <span class="ml-2 font-mono">{loop.stopped_reason}</span></span
    >
    <span
      ><span class="text-muted-foreground">Total</span>
      <span class="ml-2 font-mono">{stats.totalLabel}</span></span
    >
    <span
      ><span class="text-muted-foreground">Accumulated</span>
      <span class="ml-2 font-mono">{stats.accumulatedLabel}</span></span
    >
  </div>
</div>
