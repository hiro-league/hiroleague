<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { Microscope, Share2 } from '@lucide/svelte';
  import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/eval';
  import Highlight from '$lib/search/Highlight.svelte';
  import { approxTokens, fmtCompact, fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import { CORPUS_CLAMP_MAX_HEIGHT } from '$lib/features/eval/shared/eval-corpus-review-pure';

  interface Props {
    ep: EvalEpisode;
    episodeNo: number;
    compact: boolean;
    enhanced: boolean;
    stickyTop?: string;
    search: string;
    renderMarkdown: boolean;
    collapsed: boolean;
    showExpandToggle: boolean;
    expanded: boolean;
    extraction?: Record<string, CorpusEpisodeExtraction>;
    onOpenPipeline?: (info: { id: string; runId: string; stepIndex: number | '' }) => void;
    onOpenGraph?: (info: { id: string }) => void;
    onToggleExpand: () => void;
    register: (node: HTMLElement, id: string) => { destroy: () => void };
  }

  let {
    ep,
    episodeNo,
    compact,
    enhanced,
    stickyTop,
    search,
    renderMarkdown,
    collapsed,
    showExpandToggle,
    expanded,
    extraction,
    onOpenPipeline,
    onOpenGraph,
    onToggleExpand,
    register
  }: Props = $props();
</script>

<div
  use:register={ep.id}
  data-ep-id={ep.id}
  class="border-t border-border {compact ? 'px-3 py-1.5' : 'px-3 py-2'} first:border-t-0 odd:bg-muted/40"
  style={enhanced && stickyTop ? `scroll-margin-top: calc(${stickyTop} + 3.5rem);` : undefined}
>
  <div
    class={compact
      ? 'flex flex-wrap items-center gap-2 font-sans text-[11px] text-muted-foreground'
      : '-mx-3 -mt-2 mb-2 flex flex-wrap items-center gap-2 border-b border-border bg-muted px-3 py-1.5 font-sans text-[11px] text-muted-foreground'}
  >
    <span class="font-mono text-sm font-semibold text-foreground tabular-nums">#{episodeNo}</span>
    {#if ep.speaker}<Badge variant="outline" class="font-sans normal-case">{ep.speaker}</Badge>{/if}
    <span class="font-mono">{ep.id}</span>
    <span class="font-mono tabular-nums">{fmtEpisodeDate(ep.timestamp)}</span>
    <span
      class="font-mono tabular-nums text-muted-foreground/70"
      title="Approximate tokens (≈ chars / 4)"
    >~{fmtCompact(approxTokens(ep.body))} tok</span>
    {#if extraction}
      {@const x = extraction[ep.id]}
      {#if x === undefined}
        <span class="font-sans text-muted-foreground/70">no trace</span>
      {:else if x.entity_count === 0 && x.fact_count === 0}
        <Badge
          variant="outline"
          class="border-amber-400/60 font-sans normal-case text-amber-600 dark:text-amber-400"
        >no extraction</Badge>
      {:else}
        <span class="font-mono tabular-nums">
          <span class="font-medium text-emerald-600 dark:text-emerald-400">{x.entity_count} entities</span>
          <span class="text-muted-foreground/60"> · </span>
          <span class="font-medium text-violet-600 dark:text-violet-400">{x.fact_count} facts</span>
        </span>
      {/if}
      {#if x !== undefined && x.run_id && onOpenPipeline}
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-sans text-[10px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
          title="Open the ingestion pipeline trace for this episode"
          onclick={() => onOpenPipeline?.({ id: ep.id, runId: x.run_id, stepIndex: x.step_index })}
        >
          <Microscope size={11} aria-hidden="true" />
          pipeline
        </button>
      {/if}
      {#if onOpenGraph}
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-0.5 font-sans text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
          title="Open this episode in the Knowledge Graph (filtered to its entities/facts)"
          onclick={() => onOpenGraph?.({ id: ep.id })}
        >
          <Share2 size={11} aria-hidden="true" />
          graph
        </button>
      {/if}
    {/if}
  </div>
  <div style={collapsed ? `max-height: ${CORPUS_CLAMP_MAX_HEIGHT}; overflow: hidden;` : undefined}>
    {#if renderMarkdown}
      <MarkdownPreview markdown={ep.body} compact class="text-[13px]" />
    {:else}
      <p class="whitespace-pre-wrap font-sans text-[13px] leading-6">
        <Highlight text={ep.body} query={search} />
      </p>
    {/if}
  </div>
  {#if showExpandToggle}
    <button
      type="button"
      class="mt-1 font-sans text-xs font-medium text-primary hover:underline"
      onclick={onToggleExpand}
    >
      {expanded ? 'Show less' : 'Show more'}
    </button>
  {/if}
</div>
