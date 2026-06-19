<script lang="ts">
  import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/eval';
  import EvalCorpusEpisodeRow from '$lib/features/eval/view/corpus-review/EvalCorpusEpisodeRow.svelte';
  import type { CorpusClamp } from '$lib/features/eval/state/eval-corpus-clamp.svelte';
  import type { CorpusScrollAnchor } from '$lib/features/eval/state/eval-corpus-scroll-anchor.svelte';

  interface Props {
    filtered: EvalEpisode[];
    episodeNo: Map<string, number>;
    search: string;
    countFilterActive: boolean;
    compact: boolean;
    enhanced: boolean;
    stickyTop?: string;
    renderMarkdown: boolean;
    searching: boolean;
    extraction?: Record<string, CorpusEpisodeExtraction>;
    onOpenPipeline?: (info: { id: string; runId: string; stepIndex: number | '' }) => void;
    onOpenGraph?: (info: { id: string }) => void;
    clamp: CorpusClamp;
    scrollAnchor: CorpusScrollAnchor;
  }

  let {
    filtered,
    episodeNo,
    search,
    countFilterActive,
    compact,
    enhanced,
    stickyTop,
    renderMarkdown,
    searching,
    extraction,
    onOpenPipeline,
    onOpenGraph,
    clamp,
    scrollAnchor
  }: Props = $props();
</script>

{#if filtered.length === 0}
  <p class="px-3 py-2 font-sans text-xs text-muted-foreground">
    {#if search.trim() || countFilterActive}No episodes match the current filters.{:else}No episodes.{/if}
  </p>
{:else}
  {#each filtered as ep (ep.id)}
    <EvalCorpusEpisodeRow
      {ep}
      episodeNo={episodeNo.get(ep.id) ?? 0}
      {compact}
      {enhanced}
      {stickyTop}
      {search}
      {renderMarkdown}
      collapsed={clamp.isCollapsed(ep, enhanced, searching)}
      showExpandToggle={enhanced && !searching && clamp.needsClamp(ep)}
      expanded={clamp.expanded.has(ep.id)}
      {extraction}
      {onOpenPipeline}
      {onOpenGraph}
      onToggleExpand={() => clamp.toggleExpand(ep.id)}
      register={scrollAnchor.register}
    />
  {/each}
{/if}
