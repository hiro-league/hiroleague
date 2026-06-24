<script lang="ts">
  import { BookText, Code, ExternalLink, LoaderCircle, Search } from '@lucide/svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import KnowledgeAskFilterBar from '$lib/features/knowledge/ask/KnowledgeAskFilterBar.svelte';
  import KnowledgeAskCompareView from '$lib/features/knowledge/ask/KnowledgeAskCompareView.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import KnowledgeChunkMarkdownPreview from '$lib/features/knowledge/shared/KnowledgeChunkMarkdownPreview.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import type { KnowledgeSource } from '$lib/api/knowledge';
  import {
    chunkTextByteSize,
    formatBytes,
    readKnowledgeChunkMarkdownFormat,
    writeKnowledgeChunkMarkdownFormat
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_ASK_CHUNK_RESULTS_BODY_ID,
    KNOWLEDGE_ASK_QUESTION_BODY_ID,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT_LG
  } from '$lib/features/knowledge/shared/knowledge-ui';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ask = $derived(ctl.ask);
  const options = $derived(ctl.options);

  let chunkMarkdownFormat = $state(readKnowledgeChunkMarkdownFormat());

  // L3 (Phase 5d): in compare mode we show the compareResult, otherwise the single answerResult.
  // The cached "opposite-mode" result stays available — switching modes after a search reveals
  // the previously cached result for the new mode without re-asking.
  const inCompareMode = $derived(ask.graphMode === 'compare');
  const activeResult = $derived(inCompareMode ? ask.compareResult : ask.answerResult);

  const questionHeaderSummary = $derived(
    ask.searching
      ? 'Searching…'
      : !activeResult
        ? ''
        : inCompareMode
          ? ask.compareResult?.both_no_results
            ? 'No sources matched (both legs)'
            : 'Compare ready'
          : ask.answerResult?.no_results
            ? 'No sources matched'
            : 'Answer ready'
  );

  // Explain-mode hints. matchKind is null in the default path (no per-branch scores), so the
  // row falls back to the plain score badge and renders no extra detail.
  type MatchKind = 'both' | 'semantic' | 'keyword' | null;
  const MATCH_LABEL: Record<'both' | 'semantic' | 'keyword', string> = {
    both: 'Both',
    semantic: 'Semantic',
    keyword: 'Keyword'
  };

  function matchKind(source: KnowledgeSource): MatchKind {
    const hasDense = source.dense_score != null;
    const hasSparse = source.sparse_score != null;
    if (hasDense && hasSparse) return 'both';
    if (hasDense) return 'semantic';
    if (hasSparse) return 'keyword';
    return null;
  }

  // Score coloring (hybrid scheme). Cosine is a bounded 0–1 similarity, so it uses fixed
  // bands — 0.6 means the same thing on every query. BM25 and the RRF score are unbounded /
  // rank-based, so they're colored relative to the strongest result in the *current* set.
  type ScoreTone = 'strong' | 'ok' | 'weak';

  // Reuse the design-system Badge variants (emerald / amber / neutral fill) for chip color.
  const TONE_VARIANT: Record<ScoreTone, 'success' | 'warning' | 'secondary'> = {
    strong: 'success',
    ok: 'warning',
    weak: 'secondary'
  };
  // Bar-fill color for the RRF strength slider (a plain div, not a Badge).
  const TONE_BAR: Record<ScoreTone, string> = {
    strong: 'bg-emerald-500',
    ok: 'bg-amber-500',
    weak: 'bg-muted-foreground/40'
  };

  function cosineTone(score: number): ScoreTone {
    if (score >= 0.6) return 'strong';
    if (score >= 0.45) return 'ok';
    return 'weak';
  }

  function relativeTone(value: number, max: number): ScoreTone {
    if (max <= 0) return 'weak';
    const ratio = value / max;
    if (ratio >= 0.85) return 'strong';
    if (ratio >= 0.6) return 'ok';
    return 'weak';
  }

  // True when a reranker reordered this answer's chunks (any source tagged score_source
  // 'reranker'). Drives the "Reranked" header chip and the per-row rerank relevance badge.
  const reranked = $derived(
    (ask.answerResult?.sources ?? []).some((source) => source.score_source === 'reranker')
  );

  // Set-relative maxima for the rank-based scores (RRF + BM25), recomputed per answer.
  const topScore = $derived(
    (ask.answerResult?.sources ?? []).reduce((max, source) => Math.max(max, source.score ?? 0), 0)
  );
  const maxSparseScore = $derived(
    (ask.answerResult?.sources ?? []).reduce((max, source) => Math.max(max, source.sparse_score ?? 0), 0)
  );
</script>

<section class="grid gap-4">
  <AdminPageStickyToolbar>
    <KnowledgeAskFilterBar {ask} {options} />
  </AdminPageStickyToolbar>

  <KnowledgeCollapsibleSectionCard
    title="Question"
    bodyId={KNOWLEDGE_ASK_QUESTION_BODY_ID}
    defaultExpanded={true}
    summary={questionHeaderSummary}
  >
    <div class="flex flex-wrap items-end gap-3">
      <label class="grid min-w-[320px] flex-1 gap-1 font-sans text-sm">
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Question</span>
        <input
          class={KNOWLEDGE_INPUT_LG}
          bind:this={ask.queryInputEl}
          bind:value={ask.query}
          onkeydown={(event) => {
            if (event.key === 'Enter') void ask.runSearch();
          }}
        />
      </label>
      <Button onclick={() => void ask.runSearch()} disabled={ask.searching || !ask.query.trim()}>
        {#if ask.searching}
          <LoaderCircle size={16} class="animate-spin" />
        {:else}
          <Search size={16} />
        {/if}
        Ask
      </Button>
      {#if activeResult}
        <!-- Drop the cached answer + chunks (both single + compare) so the next question starts fresh. -->
        <Button variant="outline" onclick={ask.clearAnswer} disabled={ask.searching}>
          Clear
        </Button>
      {/if}
    </div>

    {#if ask.askDocumentScope}
      <div class="flex flex-wrap items-center gap-2 rounded-md border bg-background px-3 py-2 font-sans text-sm">
        <span class="text-muted-foreground">Scoped to document:</span>
        <Badge variant="secondary">{ask.askDocumentScope.title || ask.askDocumentScope.source_uri}</Badge>
        <Button class="h-7 px-2" variant="ghost" onclick={ask.clearAskDocumentScope}>Clear scope</Button>
      </div>
    {/if}

    {#if inCompareMode && ask.compareResult}
      <!-- L3 compare-mode: render the two-leg side-by-side view. -->
      <KnowledgeAskCompareView compareResult={ask.compareResult} />
    {:else if inCompareMode}
      <InlineEmptyState
        message="Ask a question to compare flat vs graph-augmented retrieval side-by-side."
        hint={!ask.askRewrite
          ? 'Tip: enable Rewrite — graph mode needs entities from the rewrite step.'
          : undefined}
        class="border-solid bg-background px-3 py-8"
      />
    {:else if ask.answerResult?.no_results}
      <InlineEmptyState
        message="No sources matched. Relax filters or lower the minimum score."
        class="border-solid bg-background px-3 py-8"
      />
    {:else if ask.answerResult}
      <article class="grid gap-3 rounded-md border bg-background p-4">
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{ask.answerResult.elapsed_ms}ms</Badge>
          {#if ask.answerResult.model_id}<Badge variant="secondary">{ask.answerResult.model_id}</Badge>{/if}
          {#if reranked}
            <Badge variant="secondary" title="Chunks reordered by a cross-encoder reranker">
              Reranked
            </Badge>
          {/if}
          {#if ask.answerResult.usage?.usage_available}
            <Badge variant="outline">
              {(ask.answerResult.usage.input_tokens ?? ask.answerResult.usage.estimated_input_tokens ?? 0)} in /
              {(ask.answerResult.usage.output_tokens ?? 0)} out
            </Badge>
          {/if}
          {#if ask.answerResult.run_id}
            <a
              class="inline-flex items-center gap-1 rounded-md border px-2 py-1 font-sans text-xs text-primary hover:bg-primary/5"
              href={graphRunPageUrl(ask.answerResult.run_id)}
              title={ask.answerResult.run_id}
            >
              <ExternalLink size={12} aria-hidden="true" />
              Graph run
            </a>
          {/if}
          <Button
            class="ml-auto h-8"
            variant="outline"
            onclick={() => navigator.clipboard?.writeText(ask.answerResult?.answer ?? '')}
          >
            Copy answer
          </Button>
        </div>
        {#if ask.answerResult.rewritten_query}
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-dashed bg-muted/30 px-3 py-2 font-sans text-xs">
            <span class="shrink-0 font-medium text-muted-foreground">Searched as</span>
            <span class="min-w-0 break-words text-foreground">{ask.answerResult.rewritten_query}</span>
            {#if ask.answerResult.keywords?.length}
              <span class="ml-1 shrink-0 text-muted-foreground">keywords:</span>
              {#each ask.answerResult.keywords as kw (kw)}
                <Badge variant="secondary" class="rounded px-1.5 py-0 font-mono text-[12px]">{kw}</Badge>
              {/each}
            {/if}
          </div>
        {/if}
        <p class="whitespace-pre-wrap font-sans text-sm leading-6">{ask.answerResult.answer}</p>
      </article>
    {:else}
      <InlineEmptyState
        message="Ask a question to retrieve cited sources."
        class="border-solid bg-background px-3 py-8"
      />
    {/if}
  </KnowledgeCollapsibleSectionCard>

  <!-- Chunk-Results section is single-mode only — compare view shows compact source
       summaries inline per leg, double-rendering the full chunk grid would dominate the
       screen and slow scrolling. -->
  {#if !inCompareMode && ask.answerResult && !ask.answerResult.no_results && ask.answerResult.sources.length > 0}
    <KnowledgeCollapsibleSectionCard
      title="Chunk Results"
      bodyId={KNOWLEDGE_ASK_CHUNK_RESULTS_BODY_ID}
      defaultExpanded={false}
      summary={`${ask.answerResult.sources.length} chunks`}
    >
      {#snippet headerActions()}
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0 text-muted-foreground hover:text-foreground"
          type="button"
          aria-label={chunkMarkdownFormat ? 'Show raw chunk text' : 'Show formatted markdown'}
          aria-pressed={chunkMarkdownFormat}
          title={chunkMarkdownFormat ? 'Formatted markdown — click for raw text' : 'Raw text — click for formatted markdown'}
          onclick={() => {
            chunkMarkdownFormat = !chunkMarkdownFormat;
            writeKnowledgeChunkMarkdownFormat(chunkMarkdownFormat);
          }}
        >
          {#if chunkMarkdownFormat}
            <BookText size={16} aria-hidden="true" />
          {:else}
            <Code size={16} aria-hidden="true" />
          {/if}
        </Button>
      {/snippet}
      <div class="rounded-md border">
        {#each ask.answerResult.sources as source (source.point_id)}
          {@const kind = matchKind(source)}
          {@const rrfTone = relativeTone(source.score, topScore)}
          <article class="grid gap-2 border-t px-3 py-3 first:border-t-0">
            <div class="flex min-w-0 items-center gap-2">
              <Badge class="shrink-0 rounded-md font-mono tabular-nums" variant="secondary">#{source.ref}</Badge>
              <span class="min-w-0 truncate font-sans text-sm font-medium">{source.title}</span>
              {#if source.heading_path}
                <span class="min-w-0 truncate font-sans text-xs text-muted-foreground">{source.heading_path}</span>
              {/if}
              {#if kind}
                <Badge class="ml-auto shrink-0 font-mono" variant={kind === 'both' ? 'default' : 'outline'}>
                  {MATCH_LABEL[kind]}
                </Badge>
              {/if}
              <!-- RRF strength slider: fill width + color are relative to the top result in this set. -->
              <div
                class="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted {kind ? '' : 'ml-auto'}"
                title="RRF score relative to the top result"
              >
                <div
                  class="h-full rounded-full transition-[width] {TONE_BAR[rrfTone]}"
                  style="width: {topScore > 0 ? Math.round((source.score / topScore) * 100) : 0}%"
                ></div>
              </div>
              {#if source.rerank_score != null}
                <Badge
                  class="shrink-0 font-mono tabular-nums"
                  variant={TONE_VARIANT[cosineTone(source.relevance ?? 0)]}
                  title={`Reranker relevance (normalized; raw score ${source.rerank_score.toFixed(3)})`}
                >
                  rerank {(source.relevance ?? 0).toFixed(3)}
                </Badge>
              {/if}
              <Badge
                class="shrink-0 font-mono tabular-nums {source.rerank_score != null
                  ? 'opacity-60'
                  : ''}"
                variant={TONE_VARIANT[rrfTone]}
                title="Retrieval (RRF) score — relative to the top result"
              >
                {source.score.toFixed(3)}
              </Badge>
              <Badge class="shrink-0 font-mono tabular-nums" variant="outline">
                {formatBytes(chunkTextByteSize(source.text))}
              </Badge>
            </div>
            {#if kind}
              <div class="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
                {#each source.matched_terms ?? [] as term (term)}
                  <Badge variant="secondary" class="rounded px-1.5 py-0 font-mono text-[12px]">{term}</Badge>
                {/each}
                {#if source.dense_score != null}
                  <Badge
                    variant={TONE_VARIANT[cosineTone(source.dense_score)]}
                    class="rounded px-1.5 py-0 font-mono text-[12px] tabular-nums"
                  >
                    cos {source.dense_score.toFixed(3)}
                  </Badge>
                {/if}
                {#if source.sparse_score != null}
                  <Badge
                    variant={TONE_VARIANT[relativeTone(source.sparse_score, maxSparseScore)]}
                    class="rounded px-1.5 py-0 font-mono text-[12px] tabular-nums"
                  >
                    bm25 {source.sparse_score.toFixed(2)}
                  </Badge>
                {/if}
              </div>
            {/if}
            {#if chunkMarkdownFormat}
              <KnowledgeChunkMarkdownPreview markdown={source.text} class="text-muted-foreground" />
            {:else}
              <p class="whitespace-pre-wrap font-sans text-sm leading-6 text-muted-foreground">{source.text}</p>
            {/if}
          </article>
        {/each}
      </div>
    </KnowledgeCollapsibleSectionCard>
  {/if}
</section>
