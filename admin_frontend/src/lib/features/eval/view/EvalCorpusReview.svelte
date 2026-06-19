<!--
  Reusable corpus transcript with search + match highlight.

  Renders the memory-eval corpus episodes as a dated transcript, with a search box that filters to
  matching episodes and highlights the term in the body. Used in two places:
    1. The Eval panel's "Corpus" section (review the turns the questions probe).
    2. A "Corpus" tab inside the retrieval/ingest trace dialogs (cross-reference a recalled/
       ingested fact against its source episode while inspecting the pipeline).

  The "enhanced" reading affordances (Markdown toggle, per-episode line clamp + show more/less,
  sticky episode index rail, position readout) only render in the Corpus-tab layout (when
  `stickyTop` is set). The compact trace-dialog tab stays a dense plain-text transcript.
-->
<script lang="ts">
  import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/eval';
  import {
    buildEpisodeNoMap,
    filterCorpusEpisodes
  } from '$lib/features/eval/shared/eval-corpus-review-pure';
  import {
    EVAL_TOOLBAR_SEARCH,
    EVAL_TOOLBAR_SEARCH_INPUT
  } from '$lib/features/eval/shared/eval-table-ui';
  import { createCorpusClamp } from '$lib/features/eval/state/eval-corpus-clamp.svelte';
  import { createCorpusExtractionFilters } from '$lib/features/eval/state/eval-corpus-extraction-filters.svelte';
  import { createCorpusScrollAnchor } from '$lib/features/eval/state/eval-corpus-scroll-anchor.svelte';
  import EvalCorpusEpisodeList from '$lib/features/eval/view/corpus-review/EvalCorpusEpisodeList.svelte';
  import EvalCorpusExtractionFilters from '$lib/features/eval/view/corpus-review/EvalCorpusExtractionFilters.svelte';
  import EvalCorpusIndexRail from '$lib/features/eval/view/corpus-review/EvalCorpusIndexRail.svelte';
  import EvalCorpusReviewToolbar from '$lib/features/eval/view/corpus-review/EvalCorpusReviewToolbar.svelte';

  let {
    episodes,
    compact = false,
    search = $bindable(''),
    showSearch = true,
    showCount = false,
    scroll = true,
    extraction,
    onOpenPipeline,
    onOpenGraph,
    stickyTop,
    markdownMode = $bindable(false)
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
    markdownMode?: boolean;
  } = $props();

  const enhanced = $derived(stickyTop !== undefined);
  const searching = $derived(!!search.trim());
  const renderMarkdown = $derived(markdownMode && !searching);

  const episodeNo = $derived(buildEpisodeNoMap(episodes));

  const filters = createCorpusExtractionFilters(() => extraction);
  const filtered = $derived(
    filterCorpusEpisodes(
      episodes,
      search,
      extraction,
      filters.filterState,
      filters.maxEnt,
      filters.maxFact
    )
  );

  const clamp = createCorpusClamp(() => episodes);
  const scrollAnchor = createCorpusScrollAnchor({
    getEnabled: () => enhanced,
    getFiltered: () => filtered
  });

  const currentNo = $derived(
    episodeNo.get(scrollAnchor.currentId ?? filtered[0]?.id ?? '') ?? null
  );

  function toggleMarkdown() {
    markdownMode = !markdownMode;
  }
</script>

<div class="grid gap-2">
  {#if stickyTop !== undefined}
    <EvalCorpusReviewToolbar
      {stickyTop}
      {search}
      onSearchChange={(v) => (search = v)}
      {filters}
      hasExtraction={filters.hasExtraction}
      {markdownMode}
      onToggleMarkdown={toggleMarkdown}
      {searching}
      countFilterActive={filters.countFilterActive}
      filteredCount={filtered.length}
      totalCount={episodes.length}
      {currentNo}
      onExpandAll={() => clamp.expandAll(filtered)}
      onCollapseAll={clamp.collapseAll}
    />
    <div class="flex items-start gap-3">
      <EvalCorpusIndexRail {filtered} {episodeNo} {stickyTop} {scrollAnchor} />
      <div class="min-w-0 flex-1 rounded-md border">
        <EvalCorpusEpisodeList
          {filtered}
          {episodeNo}
          {search}
          countFilterActive={filters.countFilterActive}
          {compact}
          {enhanced}
          {stickyTop}
          {renderMarkdown}
          {searching}
          {extraction}
          {onOpenPipeline}
          {onOpenGraph}
          {clamp}
          {scrollAnchor}
        />
      </div>
    </div>
  {:else}
    {#if showSearch}
      <div class="flex flex-wrap items-center gap-2">
        <label class={EVAL_TOOLBAR_SEARCH}>
          <input
            class={EVAL_TOOLBAR_SEARCH_INPUT}
            placeholder="Search episodes…"
            bind:value={search}
          />
        </label>
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
    {#if filters.hasExtraction}
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/30 px-3 py-2">
        <EvalCorpusExtractionFilters {filters} />
      </div>
    {/if}
    <div class="rounded-md border {compact || !scroll ? '' : 'max-h-96 overflow-y-auto'}">
      <EvalCorpusEpisodeList
        {filtered}
        {episodeNo}
        {search}
        countFilterActive={filters.countFilterActive}
        {compact}
        enhanced={false}
        {renderMarkdown}
        {searching}
        {extraction}
        {onOpenPipeline}
        {onOpenGraph}
        {clamp}
        {scrollAnchor}
      />
    </div>
  {/if}
</div>
