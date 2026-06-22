<!--
  Turn-by-turn retrieval-agent trajectory for one memory-eval recall leg (P8).
  Each search row shows its query and a "Trace" button that opens the full retrieval pipeline
  dialog for that sub-query (via onOpenTrace → eval-traces.openTraceForSubQuery, matched on sid).
  Clicking the row body highlights the matching facts in the sibling Facts tab.
-->
<script lang="ts">
  import { FileSearch, LoaderCircle } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { RecalledFact } from '$lib/features/eval/shared/eval-events';
  import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';
  import { trajectoryStats } from './eval-trajectory-controller.svelte';

  interface Props {
    loop: RetrievalLoop;
    facts: RecalledFact[];
    onSearchSelect: (sid: number) => void;
    /** Open the full pipeline trace for sub-query `sid`. Undefined when the leg has no run_id. */
    onOpenTrace?: (sid: number) => void;
    /** sid whose pipeline trace is currently loading (drives the per-row spinner). */
    loadingSid?: number | null;
  }
  let { loop, facts, onSearchSelect, onOpenTrace, loadingSid = null }: Props = $props();

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
      <div class="flex items-center gap-2 pl-4">
        <button
          type="button"
          class="grid flex-1 grid-cols-[56px_1fr_auto_auto] items-center gap-x-3 gap-y-1 text-left hover:bg-muted/40"
          title={`Highlight facts retrieved by S${c.sid}`}
          onclick={() => onSearchSelect(c.sid)}
        >
          <span class="font-mono text-muted-foreground">S{c.sid}</span>
          <div class="grid gap-0.5">
            <span class="text-muted-foreground italic">goal: "{c.goal}"</span>
            <span class="truncate font-mono text-[11px] text-foreground/90" title={c.query}>
              query: "{c.query}"
            </span>
            <span class="font-mono text-[11px] text-muted-foreground/80">
              {c.temporal} · limit {c.limit} · hops {c.hops}{#if c.show_expiry} · show_expiry{/if}
            </span>
          </div>
          <span class="font-mono text-muted-foreground">{c.returned} returned</span>
          <span class="rounded bg-success/15 px-2 py-0.5 font-mono text-success">+{c.new} new</span>
        </button>
        {#if onOpenTrace}
          <Button
            variant="outline"
            size="sm"
            class="h-7 shrink-0 gap-1 px-2 text-[11px]"
            disabled={loadingSid !== null}
            title={`Open the retrieval pipeline trace for S${c.sid}`}
            onclick={() => onOpenTrace(c.sid)}
          >
            {#if loadingSid === c.sid}
              <LoaderCircle size={12} class="animate-spin" aria-hidden="true" />
            {:else}
              <FileSearch size={12} aria-hidden="true" />
            {/if}
            Trace
          </Button>
        {/if}
      </div>
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
