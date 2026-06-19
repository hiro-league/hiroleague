<script lang="ts">
  import { cn } from '$lib/utils';
  import { SPARKLINE_VIEW, buildSparklinePaths, type SparklineInputSeries } from './sparkline-path';

  let {
    series,
    yMax = null,
    class: className = ''
  }: {
    series: SparklineInputSeries[];
    yMax?: number | null;
    class?: string;
  } = $props();

  const { bottom } = SPARKLINE_VIEW;

  const prepared = $derived(buildSparklinePaths(series, yMax));
</script>

<div class={cn('h-28 w-full overflow-hidden rounded-md border bg-background/40', className)}>
  <svg
    class="h-full w-full"
    viewBox="0 0 {SPARKLINE_VIEW.width} {SPARKLINE_VIEW.height}"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <line x1="0" y1={bottom} x2="100" y2={bottom} stroke="currentColor" opacity="0.12" />
    <line x1="0" y1="18" x2="100" y2="18" stroke="currentColor" opacity="0.08" />
    {#each prepared as line (line.label)}
      {#if line.path}
        <path d={line.areaPath} fill={line.color} opacity="0.14" />
        <path d={line.path} fill="none" stroke={line.color} stroke-width="1.8" vector-effect="non-scaling-stroke" />
      {/if}
    {/each}
  </svg>
</div>
