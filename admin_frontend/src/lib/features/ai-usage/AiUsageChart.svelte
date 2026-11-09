<script lang="ts">
  // Logs → AI usage (Phase 7b): one stacked bar per hour, day or week, split by what the page
  // groups by. Hovering a bar lists its parts. Ported from HomeHiro's LLM usage chart.
  import {
    colorOf,
    dayLabel,
    hourLabel,
    HOUR,
    metricText,
    shortDate,
    type Bars,
    type Metric,
    type Range
  } from './ai-usage';

  let { data, range, metric, now }: { data: Bars; range: Range; metric: Metric; now: number } = $props();

  let width = $state(800);
  const M = { left: 52, right: 8, top: 10, bottom: 24 };
  const H = 240;
  const plotH = H - M.top - M.bottom;
  const band = $derived((width - M.left - M.right) / Math.max(1, data.bars.length));
  const top = $derived(nice(data.max));
  const y = (v: number) => M.top + plotH - (top ? (v / top) * plotH : 0);
  const ticks = $derived([0, top / 2, top]);

  function nice(v: number): number {
    if (v <= 0) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
  }

  const room = $derived(Math.max(1, Math.floor(width / 70)));
  const every = $derived(Math.max(1, Math.ceil(data.bars.length / room)));
  const hoursEvery = $derived([1, 2, 3, 6, 12, 24].find((k) => data.bars.length / k <= room) ?? 24);
  const labelled = (t: number, i: number) =>
    range.step === 'hour' ? new Date(t).getHours() % hoursEvery === 0 : i % every === 0;
  const manyDays = $derived(range.step === 'hour' && data.bars.length > 24);
  const label = (t: number) =>
    range.step !== 'hour' ? shortDate(t, now) : manyDays && new Date(t).getHours() === 0 ? shortDate(t, now) : hourLabel(t);
  const when = (t: number) =>
    range.step === 'hour'
      ? `${dayLabel(t, now)}, ${hourLabel(t)}–${hourLabel(t + HOUR)}`
      : range.step === 'day'
        ? dayLabel(t, now)
        : `Week of ${dayLabel(t, now)}`;

  function stack(values: Record<string, number>) {
    const out: { k: string; y0: number; y1: number }[] = [];
    let base = 0;
    for (const k of data.keys) {
      const v = values[k] ?? 0;
      if (v) out.push({ k, y0: base, y1: base + v });
      base += v;
    }
    return out;
  }

  let hover = $state<number | null>(null);
  function move(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - M.left) / band);
    hover = i >= 0 && i < data.bars.length ? i : null;
  }
  const shown = $derived(hover === null ? null : data.bars[hover]);
</script>

<div class="grid gap-2">
  <div class="flex flex-wrap gap-x-4 gap-y-1 font-sans text-xs text-muted-foreground">
    {#each data.keys as k (k)}
      <span class="flex items-center gap-1.5"
        ><span class="size-2.5 rounded-sm" style="background:{colorOf(data.keys, k)}"></span>{k}</span
      >
    {/each}
  </div>
  <div class="relative w-full min-w-0" bind:clientWidth={width}>
    <svg
      {width}
      height={H}
      role="img"
      aria-label="AI usage over the period, stacked"
      onpointermove={move}
      onpointerleave={() => (hover = null)}
      class="block touch-none select-none"
    >
      {#each ticks as t (t)}
        <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} class="stroke-border" stroke-dasharray={t ? '2 4' : ''} />
        <text x={M.left - 6} y={y(t) + 4} text-anchor="end" class="fill-muted-foreground font-sans text-[11px]"
          >{metricText(t, metric)}</text
        >
      {/each}
      {#each data.bars as b, i (b.start)}
        {@const x = M.left + i * band + Math.min(2, band * 0.15)}
        {@const w = Math.max(1, band - 2 * Math.min(2, band * 0.15))}
        {#if hover === i}<rect x={M.left + i * band} y={M.top} width={band} height={plotH} class="fill-muted/60" />{/if}
        {#each stack(b.values) as s (s.k)}
          <rect {x} width={w} y={y(s.y1)} height={Math.max(0, y(s.y0) - y(s.y1))} fill={colorOf(data.keys, s.k)} />
        {/each}
        {#if labelled(b.start, i)}
          <text x={M.left + (i + 0.5) * band} y={H - 6} text-anchor="middle" class="fill-muted-foreground font-sans text-[11px]"
            >{label(b.start)}</text
          >
        {/if}
      {/each}
    </svg>
    {#if shown && hover !== null}
      <div
        class="pointer-events-none absolute top-2 z-10 grid min-w-52 gap-1 rounded-md border bg-popover p-2 font-sans text-xs shadow-md"
        style={M.left + hover * band > width / 2
          ? `right:${width - M.left - hover * band + 8}px`
          : `left:${M.left + (hover + 1) * band + 8}px`}
      >
        <span class="font-medium">{when(shown.start)}</span>
        {#each data.keys.filter((k) => shown.values[k]) as k (k)}
          <span class="flex items-center gap-2"
            ><span class="size-2 rounded-sm" style="background:{colorOf(data.keys, k)}"></span><span
              class="min-w-0 flex-1 truncate">{k}</span
            ><span class="tabular-nums">{metricText(shown.values[k], metric)}</span></span
          >
        {:else}
          <span class="text-muted-foreground">Nothing asked</span>
        {/each}
        {#if shown.total}<span class="flex justify-between border-t pt-1"
            ><span>Total</span><span class="tabular-nums">{metricText(shown.total, metric)}</span></span
          >{/if}
      </div>
    {/if}
  </div>
</div>
