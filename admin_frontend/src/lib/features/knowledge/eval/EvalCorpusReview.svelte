<!--
  Reusable corpus transcript with search + match highlight.

  Renders the memory-eval corpus episodes as a dated transcript, with a search box that filters to
  matching episodes and highlights the term in the body. Used in two places:
    1. The Eval panel's "Corpus" section (review the turns the questions probe).
    2. A "Corpus" tab inside the retrieval/ingest trace dialogs (cross-reference a recalled/
       ingested fact against its source episode while inspecting the pipeline).
-->
<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import GraphRangeSlider from '$lib/features/knowledge/graph/GraphRangeSlider.svelte';
  import { Microscope, Share2, X } from '@lucide/svelte';
  import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/knowledge';
  import { highlightSegments } from '$lib/features/knowledge/eval/eval-highlight';

  let {
    episodes,
    /** Compact = denser padding + smaller max-height, for the trace-dialog tab. */
    compact = false,
    /** Search term — bindable so a parent can own the input (e.g. the panel's Corpus header). */
    search = $bindable(''),
    /** Render the built-in search bar. Off when the parent supplies its own input. */
    showSearch = true,
    /** Show a standalone "N of M match" count line — used when the search input lives elsewhere
        (e.g. the trace dialog's top search drives this list, so the count surfaces here). */
    showCount = false,
    /** Bound the transcript with an inner scroll (`max-h-96`). Off ⇒ the list grows with the page
        (the panel's Corpus tab wants the page to own the scroll, not a nested box). */
    scroll = true,
    /** Per-episode at-ingest extraction (entity/fact counts + ingest-trace pointer), keyed by
        episode id. When given, each row shows an extracted/not badge; the ingest-pipeline button
        appears when `onOpenPipeline` is also wired. Omitted (the trace-dialog tab) ⇒ plain
        transcript, unchanged. */
    extraction,
    /** Open the ingest-pipeline dialog for one episode (its run_id + step_index). When set together
        with `extraction`, a "pipeline" button renders on every episode that has a trace. */
    onOpenPipeline,
    /** Open the Knowledge Graph view focused on this episode (its group + chunk_id). When set, a
        "graph" button renders on each episode (before "pipeline"). */
    onOpenGraph,
    /** When provided, render the search + filters together as ONE sticky toolbar pinned at this CSS
        `top` value (the Corpus tab passes the panel's sticky offset). Omitted ⇒ the legacy inline
        search/filter layout (the trace-dialog tab). */
    stickyTop
  }: {
    episodes: EvalEpisode[];
    compact?: boolean;
    search?: string;
    showSearch?: boolean;
    showCount?: boolean;
    scroll?: boolean;
    extraction?: Record<string, CorpusEpisodeExtraction>;
    onOpenPipeline?: (info: { id: string; runId: string; stepIndex: number | '' }) => void;
    onOpenGraph?: (info: { id: string }) => void;
    stickyTop?: string;
  } = $props();

  // 1-based episode position in the FULL corpus (stable; not the filtered subset), shown in the
  // row header. Built once per corpus so the number is the real turn ordinal regardless of search.
  const episodeNo = $derived.by(() => {
    const m = new Map<string, number>();
    episodes.forEach((ep, i) => m.set(ep.id, i + 1));
    return m;
  });

  // ---- Extraction filters (Corpus tab only; gated on `extraction` being supplied) ----
  // "Only without extraction" = traced episodes that produced 0 entities AND 0 facts. The two range
  // sliders bound entity/fact counts. All filters (checkbox + ranges + search) AND together; an
  // episode with no trace is hidden whenever any count filter is active (it has no counts to match).
  let noExtractionOnly = $state(false);
  let entRange = $state<[number, number] | null>(null);
  let factRange = $state<[number, number] | null>(null);

  const extractionValues = $derived(extraction ? Object.values(extraction) : []);
  const hasExtraction = $derived(extractionValues.length > 0);
  const maxEnt = $derived(extractionValues.reduce((m, x) => Math.max(m, x.entity_count), 0));
  const maxFact = $derived(extractionValues.reduce((m, x) => Math.max(m, x.fact_count), 0));

  // Reset the filters whenever the corpus (extraction map) changes, so switching corpus doesn't
  // carry a stale range/checkbox into a different turn set.
  $effect(() => {
    extraction; // track the map identity
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  });

  const entActive = $derived(!!entRange && (entRange[0] > 0 || entRange[1] < maxEnt));
  const factActive = $derived(!!factRange && (factRange[0] > 0 || factRange[1] < maxFact));
  const countFilterActive = $derived(noExtractionOnly || entActive || factActive);

  const filtered = $derived.by(() => {
    const term = search.trim().toLowerCase();
    let list = term
      ? episodes.filter((ep) => `${ep.body} ${ep.speaker} ${ep.id}`.toLowerCase().includes(term))
      : episodes;
    if (extraction && countFilterActive) {
      const [eLo, eHi] = entRange ?? [0, maxEnt];
      const [fLo, fHi] = factRange ?? [0, maxFact];
      list = list.filter((ep) => {
        const x = extraction[ep.id];
        if (!x) return false; // no trace ⇒ no counts to satisfy a count filter
        if (noExtractionOnly && !(x.entity_count === 0 && x.fact_count === 0)) return false;
        if (entActive && (x.entity_count < eLo || x.entity_count > eHi)) return false;
        if (factActive && (x.fact_count < fLo || x.fact_count > fHi)) return false;
        return true;
      });
    }
    return list;
  });

  function resetFilters() {
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  }

  // Episode timestamps are dated turns; show the date only (time-of-day is noise here).
  function fmtDate(iso: string): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(0, 10);
  }
</script>

<!-- Shared filter controls (checkbox + the two range sliders + reset) — rendered inside the sticky
     toolbar (Corpus tab) or the inline bar (legacy), so both layouts stay in sync. -->
{#snippet filterControls()}
  <label class="flex items-center gap-1.5 font-sans text-xs select-none">
    <input type="checkbox" bind:checked={noExtractionOnly} class="size-3.5 rounded border" />
    Only without extraction
  </label>
  {#if maxEnt > 0}
    <div class="flex items-center gap-2">
      <span class="font-sans text-xs font-medium text-emerald-600 dark:text-emerald-400">Entities</span>
      <div class="w-28">
        <GraphRangeSlider
          min={0}
          max={maxEnt}
          step={1}
          value={entRange ?? [0, maxEnt]}
          format={(v) => String(v)}
          onChange={(lo, hi) => (entRange = [lo, hi])}
        />
      </div>
    </div>
  {/if}
  {#if maxFact > 0}
    <div class="flex items-center gap-2">
      <span class="font-sans text-xs font-medium text-violet-600 dark:text-violet-400">Facts</span>
      <div class="w-28">
        <GraphRangeSlider
          min={0}
          max={maxFact}
          step={1}
          value={factRange ?? [0, maxFact]}
          format={(v) => String(v)}
          onChange={(lo, hi) => (factRange = [lo, hi])}
        />
      </div>
    </div>
  {/if}
  {#if countFilterActive}
    <button
      type="button"
      class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
      onclick={resetFilters}
    >
      Reset filters
    </button>
  {/if}
{/snippet}

<div class="grid gap-2">
  {#if stickyTop !== undefined}
    <!-- Corpus tab: search + all extraction filters on ONE sticky line, pinned under the page
         header/sub-tabs. The corpus stats line lives in the panel and scrolls away normally. -->
    <div
      class="sticky z-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-background px-3 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/90"
      style="top: {stickyTop};"
    >
      <div class="relative">
        <input
          class="h-7 w-56 rounded-md border bg-background pl-2 pr-7 font-sans text-xs"
          placeholder="Search episodes…"
          bind:value={search}
        />
        {#if search.trim()}
          <button
            type="button"
            class="absolute inset-y-0 right-1.5 my-auto flex size-4 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            onclick={() => (search = '')}
            title="Clear search"
            aria-label="Clear search"
          >
            <X size={12} aria-hidden="true" />
          </button>
        {/if}
      </div>
      {#if hasExtraction}{@render filterControls()}{/if}
      {#if search.trim() || countFilterActive}
        <span class="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">{filtered.length}/{episodes.length}</span>
      {/if}
    </div>
  {:else}
    {#if showSearch}
      <div class="flex flex-wrap items-center gap-2">
        <input
          class="h-7 w-56 rounded-md border bg-background px-2 font-sans text-xs"
          placeholder="Search episodes…"
          bind:value={search}
        />
        {#if search.trim()}
          <span class="font-sans text-xs text-muted-foreground">
            {filtered.length} of {episodes.length} match
          </span>
          <button
            type="button"
            class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
            onclick={() => (search = '')}
          >
            Clear
          </button>
        {/if}
      </div>
    {/if}
    {#if showCount}
      <span class="font-sans text-xs text-muted-foreground">
        {#if search.trim()}{filtered.length} of {episodes.length} match{:else}{episodes.length} episodes{/if}
      </span>
    {/if}
    {#if hasExtraction}
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/30 px-3 py-2">
        {@render filterControls()}
      </div>
    {/if}
  {/if}
  <!-- Compact (trace-dialog tab) or scroll=false (Corpus tab): no inner scroll — an outer region
       owns the scroll, so there's a single scrollbar instead of a nested one. -->
  <div class="rounded-md border {compact || !scroll ? '' : 'max-h-96 overflow-y-auto'}">
    {#if filtered.length === 0}
      <p class="px-3 py-2 font-sans text-xs text-muted-foreground">
        {#if search.trim() || countFilterActive}No episodes match the current filters.{:else}No episodes.{/if}
      </p>
    {:else}
      {#each filtered as ep (ep.id)}
        <!-- Zebra striping is a clearer row separator than a faint hairline, with zero extra
             vertical space (just a tint on alternate rows). -->
        <div class="border-t border-border {compact ? 'px-3 py-1.5' : 'px-3 py-2'} first:border-t-0 odd:bg-muted/40">
          <div class="flex flex-wrap items-center gap-2 font-sans text-[11px] text-muted-foreground">
            <!-- Episode # (1-based corpus position) — larger, leading the header. -->
            <span class="font-mono text-sm font-semibold text-foreground tabular-nums">#{episodeNo.get(ep.id)}</span>
            <span class="font-mono">{ep.id}</span>
            <span class="font-mono tabular-nums">{fmtDate(ep.timestamp)}</span>
            {#if ep.speaker}<Badge variant="outline" class="font-sans normal-case">{ep.speaker}</Badge>{/if}
            {#if extraction}
              {@const x = extraction[ep.id]}
              {#if x === undefined}
                <!-- No ingest trace for this episode (corpus ingested with tracing off, or not yet
                     remembered) — say so rather than implying "extracted nothing". -->
                <span class="font-sans text-muted-foreground/70">no trace</span>
              {:else if x.entity_count === 0 && x.fact_count === 0}
                <Badge variant="outline" class="border-amber-400/60 font-sans normal-case text-amber-600 dark:text-amber-400">no extraction</Badge>
              {:else}
                <!-- Entities/facts in distinct accent colors so the two counts read apart at a glance. -->
                <span class="font-mono tabular-nums">
                  <span class="font-medium text-emerald-600 dark:text-emerald-400">{x.entity_count} entities</span>
                  <span class="text-muted-foreground/60"> · </span>
                  <span class="font-medium text-violet-600 dark:text-violet-400">{x.fact_count} facts</span>
                </span>
              {/if}
              {#if onOpenGraph}
                <!-- Graph button (before pipeline): open the Knowledge Graph filtered to this
                     episode's entities/facts (its group + chunk_id). -->
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-sans text-[10px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
                  title="Open this episode in the Knowledge Graph (filtered to its entities/facts)"
                  onclick={() => onOpenGraph?.({ id: ep.id })}
                >
                  <Share2 size={11} aria-hidden="true" />
                  graph
                </button>
              {/if}
              {#if x !== undefined && x.run_id && onOpenPipeline}
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-0.5 font-sans text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
                  title="Open the ingestion pipeline trace for this episode"
                  onclick={() => onOpenPipeline?.({ id: ep.id, runId: x.run_id, stepIndex: x.step_index })}
                >
                  <Microscope size={11} aria-hidden="true" />
                  pipeline
                </button>
              {/if}
            {/if}
          </div>
          <p class="mt-1 whitespace-pre-wrap font-sans text-sm leading-6">{#each highlightSegments(ep.body, search) as seg}{#if seg.hit}<mark class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark>{:else}{seg.text}{/if}{/each}</p>
        </div>
      {/each}
    {/if}
  </div>
</div>
