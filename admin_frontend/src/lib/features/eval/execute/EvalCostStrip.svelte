<!--
  Cost strip — its own line (NOT nested in Results) so it shows during ingestion too: the memory
  remember/graph-build phase is the priciest part and runs before any question row exists. Ingest
  cost streams in on the 'remember_done' setup event; questions accumulate live; total folds both
  (LLM + reranker; embeddings unpriced). Knowledge ingest cost is deferred (multi-run), shown "—".
-->
<script lang="ts">
  import { LoaderCircle, Microscope } from '@lucide/svelte';
  import { fmtCost } from '$lib/features/eval/shared/eval-format';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    traces: EvalTraces;
  }
  let { eval_, cfg, traces }: Props = $props();

  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Questions cost accumulates live from rows.
  const questionsCost = $derived(eval_.rows.reduce((s, r) => s + (r.cost_usd || 0), 0));
  // CUMULATIVE per-corpus ingest spend (persisted in the ingested-ranges store; survives reload).
  const ingestCostCumulative = $derived(eval_.ingested?.cost_usd ?? 0);
  // Ingest (graph-build) cost also streams live: the memory runner emits a 'remember_done' setup
  // event carrying THIS batch's folded ingest cost the moment ingestion ends.
  const ingestCostLive = $derived.by(() => {
    for (let i = eval_.setupEvents.length - 1; i >= 0; i--) {
      const c = eval_.setupEvents[i].ingest_cost_usd;
      if (typeof c === 'number') return c;
    }
    return null;
  });
  // Displayed ingest cost: while running, persisted cumulative + this batch's live cost; once
  // idle/reloaded, the persisted cumulative is authoritative.
  const ingestCost = $derived.by(() => {
    const running = eval_.status === 'starting' || eval_.status === 'running';
    if (running && ingestCostLive != null) return ingestCostCumulative + ingestCostLive;
    if (ingestCostCumulative > 0) return ingestCostCumulative;
    return eval_.summary?.ingest_cost_usd ?? ingestCostLive;
  });
  const totalCost = $derived((ingestCost ?? 0) + questionsCost);
  // "building…" only while ingestion is genuinely in flight (remember started, cost not known yet,
  // no question row yet). Once rows stream — or this isn't a rebuild — fall back to "—".
  const ingestBuilding = $derived(
    cfg.tracksIngestion &&
      ingestCost == null &&
      eval_.rows.length === 0 &&
      (eval_.status === 'starting' || eval_.status === 'running') &&
      eval_.setupEvents.some((e) => e.phase === 'remember')
  );
</script>

{#if totalCost > 0 || isBusy}
  <div class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/20 px-3 py-2 font-sans text-xs">
    <span class="font-semibold uppercase tracking-wide text-muted-foreground">Cost</span>
    <span class="font-mono text-foreground">≈ {fmtCost(totalCost)}</span>
    <span class="text-muted-foreground" title="Ingest = cumulative graph-build spend for this corpus (sum of every ingest batch; survives reload). Q = this view's question cost.">
      (ingest{cfg.tracksIngestion && ingestCostCumulative > 0 ? ' cumulative' : ''} {cfg.tracksIngestion
        ? ingestCost != null
          ? fmtCost(ingestCost)
          : ingestBuilding
            ? 'building…'
            : '—'
        : '—'} · Q {fmtCost(questionsCost)})
    </span>
    {#if cfg.tracksIngestion && eval_.ingestRunId}
      <button
        type="button"
        class="ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
        disabled={traces.ingestTraceLoading}
        onclick={() => void traces.openIngestTrace(eval_.ingestRunId!)}
        title="Open the ingest (graph-build) pipeline trace for this corpus"
      >
        {#if traces.ingestTraceLoading}
          <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
        {:else}
          <Microscope size={10} aria-hidden="true" />
        {/if}
        Ingest pipeline
      </button>
      <span class="text-[11px] text-muted-foreground">LLM + reranker · embeddings not priced</span>
    {:else}
      <span class="ml-auto text-[11px] text-muted-foreground">
        LLM + reranker · embeddings not priced
      </span>
    {/if}
  </div>
{/if}
