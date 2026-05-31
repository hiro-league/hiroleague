<!--
  L3 prototype (Phase 5d) — compare-mode answer view.

  Renders the two legs of a `KnowledgeAnswerCompareData` side-by-side: flat
  (use_graph=false) on the left, graph-augmented on the right. Each column
  shows the same surface: badges (latency · model · token usage · run id),
  the rewritten-query strip, the answer body, and a compact source count.

  Intentionally simpler than the single-mode panel — the full chunk-results
  grid stays on the single-mode path. In compare mode the user is reading
  two answers in parallel; the source count + Graph-run link is enough to
  drill in if a row is interesting. (Full chunk view would double-render
  ~50 chunks and dominate the screen.)
-->
<script lang="ts">
  import { ExternalLink } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { KnowledgeAnswerCompareData, KnowledgeAnswerData } from '$lib/api/knowledge';

  interface Props {
    compareResult: KnowledgeAnswerCompareData;
  }

  let { compareResult }: Props = $props();

  // sources_delta from the server is graph - flat; surface it as a chip so the
  // "did the graph help?" signal is visible at a glance without source-counting.
  const deltaLabel = $derived.by(() => {
    const d = compareResult.sources_delta;
    if (d === 0) return 'Δ sources 0';
    return d > 0 ? `Δ sources +${d}` : `Δ sources ${d}`;
  });
  const deltaVariant: 'success' | 'warning' | 'secondary' = $derived(
    compareResult.sources_delta > 0
      ? 'success'
      : compareResult.sources_delta < 0
        ? 'warning'
        : 'secondary'
  );
</script>

<article class="grid gap-3">
  <!-- Header strip: wall-clock + delta indicator + both-empty hint. -->
  <header class="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2">
    <Badge variant="outline">Compare · {compareResult.elapsed_ms}ms</Badge>
    <Badge variant={deltaVariant}>{deltaLabel}</Badge>
    {#if compareResult.both_no_results}
      <Badge variant="secondary">Both legs returned no results</Badge>
    {/if}
  </header>

  <!-- Two columns. Stack on narrow screens; side-by-side from `md` up. -->
  <div class="grid gap-3 md:grid-cols-2">
    {@render leg(compareResult.flat, 'Flat (graph off)', 'left')}
    {@render leg(compareResult.graph, 'Graph-augmented (on)', 'right')}
  </div>
</article>

{#snippet leg(leg: KnowledgeAnswerData, title: string, _side: 'left' | 'right')}
  <article class="grid gap-2 rounded-md border bg-background p-3">
    <header class="flex flex-wrap items-center gap-2">
      <h3 class="font-sans text-sm font-semibold">{title}</h3>
      <Badge variant="outline">{leg.elapsed_ms}ms</Badge>
      {#if leg.model_id}<Badge variant="secondary">{leg.model_id}</Badge>{/if}
      {#if leg.no_results}
        <Badge variant="secondary">no_results</Badge>
      {:else}
        <Badge variant="outline">{leg.sources.length} sources</Badge>
      {/if}
      {#if leg.usage?.usage_available}
        <Badge variant="outline">
          {(leg.usage.input_tokens ?? leg.usage.estimated_input_tokens ?? 0)}i /
          {(leg.usage.output_tokens ?? 0)}o
        </Badge>
      {/if}
      {#if leg.run_id}
        <a
          class="ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-1 font-sans text-xs text-primary hover:bg-primary/5"
          href={graphRunPageUrl(leg.run_id)}
          title={leg.run_id}
        >
          <ExternalLink size={12} aria-hidden="true" />
          Graph run
        </a>
      {/if}
    </header>

    {#if leg.rewritten_query}
      <div
        class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-dashed bg-muted/20 px-2 py-1.5 font-sans text-xs"
      >
        <span class="shrink-0 font-medium text-muted-foreground">Searched as</span>
        <span class="min-w-0 break-words text-foreground">{leg.rewritten_query}</span>
        {#if leg.keywords?.length}
          <span class="ml-1 shrink-0 text-muted-foreground">keywords:</span>
          {#each leg.keywords as kw (kw)}
            <Badge variant="secondary" class="rounded px-1.5 py-0 font-mono text-[12px]">{kw}</Badge>
          {/each}
        {/if}
      </div>
    {/if}

    {#if leg.no_results}
      <p class="rounded border px-2 py-4 text-center font-sans text-xs text-muted-foreground">
        No sources matched.
      </p>
    {:else}
      <p class="whitespace-pre-wrap font-sans text-sm leading-6">{leg.answer}</p>
    {/if}

    {#if leg.sources.length > 0}
      <!-- Compact source list — title + match-type chips would push past the
           goal of "two answers side-by-side, scannable". Full chunk grid stays
           in single-mode. -->
      <ol class="grid gap-1 pt-1 font-sans text-xs text-muted-foreground">
        {#each leg.sources.slice(0, 6) as src (src.point_id)}
          <li class="flex min-w-0 gap-2">
            <span class="shrink-0 font-mono">[{src.ref}]</span>
            <span class="min-w-0 truncate">{src.title}{src.heading_path ? ' · ' + src.heading_path : ''}</span>
            <span class="ml-auto shrink-0 font-mono tabular-nums">{src.score.toFixed(3)}</span>
          </li>
        {/each}
        {#if leg.sources.length > 6}
          <li class="font-mono text-[11px] opacity-70">… +{leg.sources.length - 6} more</li>
        {/if}
      </ol>
    {/if}
  </article>
{/snippet}
