<!--
  Corpus pane (memory track) — a human-readable look at the turn corpus the questions probe:
  a stats header (episode count / date span / tokens / chars / ingested progress) then the full
  episode transcript (EvalCorpusReview, which renders its own sticky search + filters toolbar).
  Mounted only when the Corpus sub-tab is active; renders nothing on tracks without a corpus review.
-->
<script lang="ts">
  import { LoaderCircle } from '@lucide/svelte';
  import EvalCorpusReview from '$lib/features/eval/view/EvalCorpusReview.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { fmtCompact, fmtCount, fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    traces: EvalTraces;
  }
  let { eval_, cfg, traces }: Props = $props();

  // Corpus date span (first → last episode) for the stats header.
  const corpusSpan = $derived.by(() => {
    const m = eval_.corpusMeta;
    if (!m || !m.first_timestamp) return '—';
    const a = fmtEpisodeDate(m.first_timestamp);
    const b = fmtEpisodeDate(m.last_timestamp);
    return a === b ? a : `${a} → ${b}`;
  });

  // Corpus text size — total characters (exact) and approx tokens (≈ chars / 4).
  const corpusChars = $derived(
    eval_.corpusEpisodes.reduce((sum, e) => sum + (e.body?.length ?? 0), 0)
  );
  const corpusTokens = $derived(Math.round(corpusChars / 4));

  // Ingested-episode readout — which turns are in the graph. Stored spans are 0-based inclusive;
  // displayed +1 as 1-based episode numbers to match the "Episodes From..To" box. Gaps stay
  // visible so a missed range shows. "not ingested yet" until the first batch lands.
  const ingestedLabel = $derived.by(() => {
    const ing = eval_.ingested;
    if (!ing || ing.count === 0) return 'not ingested yet';
    const spans = ing.ranges.map(([s, e]) => (s === e ? `${s + 1}` : `${s + 1}–${e + 1}`)).join(', ');
    const total = eval_.corpusMeta?.episode_count ?? 0;
    const totalStr = total > 0 ? `/${total}` : '';
    const batchStr = ing.batches > 1 ? ` · ${ing.batches} batches` : '';
    return `ingested ${spans} · ${ing.count}${totalStr} eps${batchStr}`;
  });

  // Episode search — bound into EvalCorpusReview (which renders the input on its sticky toolbar).
  let corpusSearch = $state('');
</script>

{#if cfg.hasCorpusReview && eval_.selectedCorpus}
  {#if eval_.corpusError}
    <InlineDestructiveAlert message={eval_.corpusError} />
  {:else if eval_.corpusEpisodes.length === 0 && !eval_.corpusLoading}
    <InlineEmptyState message="No episodes loaded." />
  {:else}
    <!-- Corpus stats line — scrolls away normally (the search + filters live on the sticky
         toolbar rendered by EvalCorpusReview below). -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
      <span class="text-muted-foreground">
        Episodes: <span class="font-mono text-foreground">{eval_.corpusMeta?.episode_count ?? 0}</span>
      </span>
      <span class="text-muted-foreground">
        Span: <span class="font-mono text-foreground">{corpusSpan}</span>
      </span>
      <span class="text-muted-foreground">
        Questions: <span class="font-mono text-foreground">{eval_.questions.length}</span>
      </span>
      <span class="text-muted-foreground" title="Approximate tokens (≈ chars / 4)">
        Tokens: <span class="font-mono text-foreground tabular-nums">~{fmtCompact(corpusTokens)}</span>
      </span>
      <span class="text-muted-foreground">
        Characters: <span class="font-mono text-foreground tabular-nums">{fmtCount(corpusChars)}</span>
      </span>
      <span class="text-muted-foreground">
        Ingested: <span class="font-mono text-foreground">{ingestedLabel.replace(/^ingested /, '')}</span>
      </span>
      {#if eval_.corpusLoading}
        <LoaderCircle size={14} class="animate-spin text-muted-foreground" aria-hidden="true" />
      {/if}
    </div>
    <!-- Episode transcript — grows with the page (no inner scroll). EvalCorpusReview renders the
         sticky search + filters toolbar (stickyTop), the per-episode extracted/not badge, and the
         graph + pipeline buttons. -->
    <EvalCorpusReview
      episodes={eval_.corpusEpisodes}
      bind:search={corpusSearch}
      showSearch={false}
      scroll={false}
      extraction={eval_.corpusExtraction}
      onOpenPipeline={traces.openIngestTraceForEpisode}
      onOpenGraph={traces.openGraphForEpisode}
      stickyTop="calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px))"
    />
  {/if}
{/if}
