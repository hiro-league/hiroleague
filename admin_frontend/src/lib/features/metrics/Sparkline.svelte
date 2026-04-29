<script lang="ts">
  import { cn } from '$lib/utils';

  type ChartPoint = {
    ts: number;
    value: number;
  };

  type ChartSeries = {
    label: string;
    color: string;
    data: ChartPoint[];
  };

  let {
    series,
    yMax = null,
    class: className = ''
  }: {
    series: ChartSeries[];
    yMax?: number | null;
    class?: string;
  } = $props();

  const viewWidth = 100;
  const viewHeight = 36;
  const top = 3;
  const bottom = 32;

  const maxValue = $derived.by(() => {
    if (typeof yMax === 'number') return yMax;
    const values = series.flatMap((line) => line.data.map((point) => point.value));
    return Math.max(1, ...values);
  });

  const prepared = $derived.by(() =>
    series.map((line) => {
      const count = line.data.length;
      const coords = line.data.map((point, index) => {
        const x = count <= 1 ? 0 : (index / (count - 1)) * viewWidth;
        const y = bottom - (Math.max(0, point.value) / Math.max(maxValue, 1)) * (bottom - top);
        return [x, Math.max(top, Math.min(bottom, y))];
      });
      const path = coords.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
      const first = coords[0];
      const last = coords[coords.length - 1];
      return {
        ...line,
        path,
        areaPath: first && last ? `${path} L ${last[0]} ${bottom} L ${first[0]} ${bottom} Z` : ''
      };
    })
  );
</script>

<div class={cn('h-28 w-full overflow-hidden rounded-md border bg-background/40', className)}>
  <svg class="h-full w-full" viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
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
