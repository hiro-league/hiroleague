<!--
  Slim expanded fold for one answer row: per-leg stats + action buttons at the top, optional
  retrieval-loop summary, then ideal and actual LLM answers. The full diagnostic tabs
  (Overview / Evidence / Facts / Entities / Episodes / Trajectory) live in EvalRowDetailDialog,
  opened from the "Open details" button here or the ANSWER TYPE cell in the row.
-->
<script lang="ts">
  import { Maximize2 } from '@lucide/svelte';
  import EvalClampAnswer from '$lib/features/eval/answers/EvalClampAnswer.svelte';
  import EvalLegActions from '$lib/features/eval/answers/EvalLegActions.svelte';
  import { fmtCost } from '$lib/features/eval/shared/eval-format';
  import { legLabel } from '$lib/features/eval/shared/eval-display';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import { recallFoldLabel } from '$lib/features/eval/answers/eval-trajectory-controller.svelte';

  interface Props {
    r: EvalRow;
    legColumns: string[];
    /** Active answer-search term (highlights the ideal answer). */
    searchTerm: string;
    traces: EvalTraces;
    /** Open the giant detail dialog for this row. */
    onOpenDetails: () => void;
    bulkTextOpen: boolean;
    bulkTextTick: number;
  }
  let { r, legColumns, searchTerm, traces, onOpenDetails, bulkTextOpen, bulkTextTick }: Props = $props();

  const recallLeg = $derived(r.legs.recall);
</script>

<div class="grid gap-3 text-xs">
  {#each legColumns as mode, legIdx (mode)}
    {#if r.legs[mode]}
      {@const leg = r.legs[mode]}
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-2">
          {#if legColumns.length > 1}
            <span class="min-w-[48px] font-medium text-muted-foreground">{legLabel(mode)}</span>
          {/if}
          <span class="font-mono tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
          {#if leg.cost_usd}
            <span class="font-mono tabular-nums text-muted-foreground">{fmtCost(leg.cost_usd)}</span>
          {/if}
          {#if r.subcategory && legIdx === 0}
            <span class="text-muted-foreground">· {r.subcategory}</span>
          {/if}
        </div>
        <div class="flex flex-wrap items-center justify-end gap-2">
          <EvalLegActions {r} {mode} {leg} {legIdx} {traces} />
          {#if legIdx === 0}
            <button
              type="button"
              class="inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
              onclick={onOpenDetails}
              title="Open the full diagnostic detail (answer, judge, recalled facts, trajectory)"
            >
              <Maximize2 size={10} aria-hidden="true" /> Open details
            </button>
          {/if}
        </div>
      </div>
    {/if}
  {/each}

  {#if recallLeg?.retrieval_loop}
    <div class="flex flex-wrap items-start gap-2 border-t border-border pt-2">
      <span class="min-w-[48px] text-muted-foreground">Loop</span>
      <span class="font-mono text-[11px] leading-tight text-muted-foreground" title="Searches/turns · recalled facts · reduce op (with args)">
        {recallFoldLabel(recallLeg)}
      </span>
    </div>
  {/if}

  <div class="flex flex-wrap items-start gap-2 border-t border-border pt-2">
    <span class="min-w-[48px] pt-0.5 text-muted-foreground">Ideal</span>
    {#if r.gold}
      <EvalClampAnswer text={r.gold} {searchTerm} {bulkTextOpen} {bulkTextTick} />
    {:else}
      <span class="flex-1 italic text-muted-foreground">— (no ideal answer)</span>
    {/if}
  </div>

  {#each legColumns as mode (mode)}
    {#if r.legs[mode]}
      {@const leg = r.legs[mode]}
      <div class="flex flex-wrap items-start gap-2">
        <span class="min-w-[48px] pt-0.5 text-muted-foreground">
          {legColumns.length > 1 ? legLabel(mode) : 'Actual'}
        </span>
        {#if leg.answer}
          <EvalClampAnswer text={leg.answer} {searchTerm} {bulkTextOpen} {bulkTextTick} />
        {:else}
          <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
        {/if}
      </div>
    {/if}
  {/each}
</div>
