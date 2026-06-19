<script lang="ts">
  import GraphRangeSlider from '$lib/features/knowledge/graph/GraphRangeSlider.svelte';
  import type { CorpusExtractionFilters } from '$lib/features/eval/state/eval-corpus-extraction-filters.svelte';

  interface Props {
    filters: CorpusExtractionFilters;
  }
  let { filters }: Props = $props();
</script>

<label class="flex items-center gap-1.5 font-sans text-xs select-none">
  <input
    type="checkbox"
    class="size-3.5 rounded border"
    checked={filters.noExtractionOnly}
    onchange={(e) => (filters.noExtractionOnly = e.currentTarget.checked)}
  />
  Only without extraction
</label>
{#if filters.maxEnt > 0}
  <div class="flex items-center gap-2">
    <span class="font-sans text-xs font-medium text-emerald-600 dark:text-emerald-400">Entities</span>
    <div class="w-28">
      <GraphRangeSlider
        min={0}
        max={filters.maxEnt}
        step={1}
        value={filters.entRange ?? [0, filters.maxEnt]}
        format={(v) => String(v)}
        onChange={(lo, hi) => (filters.entRange = [lo, hi])}
      />
    </div>
  </div>
{/if}
{#if filters.maxFact > 0}
  <div class="flex items-center gap-2">
    <span class="font-sans text-xs font-medium text-violet-600 dark:text-violet-400">Facts</span>
    <div class="w-28">
      <GraphRangeSlider
        min={0}
        max={filters.maxFact}
        step={1}
        value={filters.factRange ?? [0, filters.maxFact]}
        format={(v) => String(v)}
        onChange={(lo, hi) => (filters.factRange = [lo, hi])}
      />
    </div>
  </div>
{/if}
{#if filters.countFilterActive}
  <button
    type="button"
    class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
    onclick={() => filters.reset()}
  >
    Reset filters
  </button>
{/if}
