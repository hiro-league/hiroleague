<!--
  Per-leg action buttons (retrieval trace · Graph-Run link · Copy-for-AI), shared by the slim fold
  (EvalResultRowDetail) and the giant detail dialog (EvalRowDetailDialog) so both surface the same
  actions. Copy is row-level — rendered once, under the first leg (legIdx === 0).
-->
<script lang="ts">
  import { Check, Copy, ExternalLink, LoaderCircle, Microscope } from '@lucide/svelte';
  import { legLabel, traceableLeg } from '$lib/features/eval/shared/eval-display';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { RowDetailTraces } from '$lib/features/eval/state/eval-traces.svelte';

  let {
    r,
    mode,
    leg,
    legIdx,
    traces
  }: {
    r: EvalRow;
    mode: string;
    leg: EvalRow['legs'][string];
    legIdx: number;
    traces: RowDetailTraces;
  } = $props();
</script>

{#if traceableLeg(mode) && leg.run_id}
  <button
    type="button"
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
    disabled={traces.traceLoadingRunId !== null}
    onclick={() => void traces.openTrace(leg.run_id!, r.gold, leg.answer, r.question)}
    title="Open the retrieval pipeline trace"
  >
    {#if traces.traceLoadingRunId === leg.run_id}
      <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
    {:else}
      <Microscope size={10} aria-hidden="true" />
    {/if}
    trace
  </button>
{/if}
{#if leg.run_id}
  <a
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
    href={graphRunPageUrl(leg.run_id)}
    title="{legLabel(mode)} Graph Run"
  >
    <ExternalLink size={10} aria-hidden="true" />{mode}
  </a>
{/if}
{#if legIdx === 0 && traces.copyRowForAI}
  <!-- Copy-for-AI needs the EvalModel (run modes / corpus / log dir), so it's absent on the
       Graph-Runs bridge controller; the button hides there rather than erroring. -->
  <button
    type="button"
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
    onclick={() => void traces.copyRowForAI?.(r)}
    title="Copy a Markdown brief (answer + judge + recalled facts inline, ledger-file pointers for the full traces) to paste into your AI agent"
  >
    {#if traces.copiedRow === r.index}
      <Check size={10} aria-hidden="true" /> Copied
    {:else}
      <Copy size={10} aria-hidden="true" /> Copy
    {/if}
  </button>
{/if}
