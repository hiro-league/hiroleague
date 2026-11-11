<script lang="ts">
  // Logs → AI usage (Phase 7b). What every paid AI call adds up to — the extensions' asks (ai.ask)
  // and Hiro's own jobs — counted by the core per hour and kept for good (`/ai/usage`). Group by one
  // dimension, filter on any of the others; a table row picked keeps only it. Each call's own
  // details stay with whoever asked (Home's AI requests log; Graph runs for Hiro).
  import { X } from '@lucide/svelte';
  import Notice from '$kit/ui/notice.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import StickyBar from '$kit/ui/sticky-bar.svelte';
  import Segmented from '$kit/ui/segmented.svelte';
  import FilterBar from '$kit/ui/filter-bar.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import MultiSelectFilter from '$lib/components/ui/multi-select-filter.svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import AiUsageChart from './AiUsageChart.svelte';
  import AiUsageRangePicker from './AiUsageRangePicker.svelte';
  import AiUsageTable from './AiUsageTable.svelte';
  import AiUsageTiles from './AiUsageTiles.svelte';
  import { AiUsagePage } from './ai-usage-page.svelte';
  import {
    DIMENSIONS,
    METRICS,
    PERIODS,
    previousLabel,
    STEPS,
    type Dimension,
    type Metric,
    type Period,
    type Step
  } from './ai-usage';

  const pg = new AiUsagePage();
  // Load the days shown (and the span before) whenever they change; filters and grouping don't load.
  $effect(() => {
    void pg.range;
    void pg.load();
  });

  const groupOptions = DIMENSIONS.map((d) => ({ value: d.value, label: d.label }));

  // The filter dropdown checks every value when nothing is filtered ("all"); the page keeps [] for "everything".
  const checked = (d: Dimension) => {
    const f = pg.filters[d] ?? [];
    return f.length ? f : pg.options[d].map((o) => o.value);
  };
  const onFilter = (d: Dimension, values: string[]) =>
    pg.setFilter(d, values.length === pg.options[d].length ? [] : values);
</script>

<div class="flex min-w-0 flex-col gap-4">
  <StickyBar class="-mx-4 border-b bg-background/85 px-4 backdrop-blur md:-mx-6 md:px-6">
    <div class="grid gap-3">
      <FilterBar class="items-center">
        <!-- The days shown: ‹ › step the picked range itself; the period buttons are shortcuts. -->
        <AiUsageRangePicker span={pg.span} now={pg.now} canLater={pg.canLater} onpick={pg.setSpan} onshift={pg.shift} />
        <Segmented label="Period" options={PERIODS} value={pg.period} onchange={(p: Period) => pg.setPeriod(p)} />

        <AdminFilterBarSelect
          label="Group by"
          layout="inline"
          value={pg.groupBy}
          options={groupOptions}
          clearable={false}
          onValueChange={(v) => (pg.groupBy = v as Dimension)}
        />
      </FilterBar>

      <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-2">
        <span class="font-sans text-xs font-semibold text-muted-foreground">Only</span>
        {#each DIMENSIONS as d (d.value)}
          <MultiSelectFilter
            label={d.label}
            options={pg.options[d.value].map((o) => ({ value: o.value, label: o.value, count: o.count }))}
            selected={checked(d.value)}
            onSelectedChange={(v) => onFilter(d.value, v)}
            searchPlaceholder="Search {d.label.toLowerCase()}…"
            class={(pg.filters[d.value]?.length ?? 0) > 0 ? 'border-primary/60 bg-primary/10' : ''}
          />
        {/each}
        {#if pg.activeFilters.length}
          <button
            type="button"
            class="inline-flex h-8 items-center gap-1 rounded-md px-2 font-sans text-xs text-muted-foreground hover:bg-accent"
            onclick={pg.clearFilters}><X size={13} /> Clear filters</button
          >
        {/if}
      </div>
    </div>
  </StickyBar>

  {#if pg.error}
    <Notice message={pg.error} />
  {:else if pg.loading && !pg.all.length}
    <Loading label="Reading AI usage…" />
  {/if}

  <AiUsageTiles now={pg.totals} before={pg.before} compared={previousLabel(pg.span, pg.now)} />

  <!-- The chart's own controls (bar size, what the bars measure) sit with the chart. -->
  <div class="grid gap-3 rounded-md border bg-card p-4 shadow-sm">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <span class="inline-flex items-center gap-2">
        <Segmented label="Measure" options={METRICS} value={pg.metric} onchange={(m: Metric) => (pg.metric = m)} />
        {#if pg.metric === 'cost'}
          <FieldHelp text="Cost here is what was billed plus what your plans' questions would cost on an API key (an estimate)." label="About cost" />
        {/if}
      </span>
      {#if pg.steps.length > 1}
        <Segmented
          label="Bars"
          options={STEPS.filter((s) => pg.steps.includes(s.value))}
          value={pg.step}
          onchange={(s: Step) => (pg.stepPicked = s)}
        />
      {/if}
    </div>
    <AiUsageChart data={pg.bars} range={pg.range} metric={pg.metric} now={pg.now} />
  </div>

  <AiUsageTable groups={pg.groups} groupBy={pg.groupBy} keys={pg.bars.keys} onpick={pg.pick} />

  <p class="font-sans text-xs text-muted-foreground">
    Counted by the core for every paid AI call it makes — questions, speech, transcription, images and embeddings — for the extensions and Hiro's own jobs, by the hour, kept for
    good. Labels are what an extension names a question (Home sends the camera or the task). A question's own details stay
    with whoever asked: Home's AI requests log, or Graph runs for Hiro. Pick a row to see only it.
  </p>
</div>
