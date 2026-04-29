<script lang="ts">
  import { onMount } from 'svelte';
  import {
    Activity,
    Cpu,
    Gauge,
    HardDrive,
    MemoryStick,
    Network,
    RefreshCw,
    Server,
    Waypoints
  } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import {
    configureMetrics,
    getMetricsTick,
    type MetricsChildRow,
    type MetricsTickResponse,
    type MetricsUiFrame
  } from '$lib/api/metrics';
  import { cn } from '$lib/utils';
  import Sparkline from './Sparkline.svelte';

  const POLL_INTERVAL_MS = 2000;
  const MAX_CHART_POINTS = 60;

  type ChartPoint = {
    ts: number;
    value: number;
  };

  let tickData = $state<MetricsTickResponse | null>(null);
  let frame = $state<MetricsUiFrame | null>(null);
  let enabled = $state(true);
  let intervalValue = $state(2);
  let loading = $state(true);
  let applying = $state(false);
  let error = $state<string | null>(null);
  let pollError = $state<string | null>(null);
  let initialized = false;
  let polling = $state(false);

  let procCpu = $state<ChartPoint[]>([]);
  let procRss = $state<ChartPoint[]>([]);
  let procThreads = $state<ChartPoint[]>([]);
  let diskRead = $state<ChartPoint[]>([]);
  let diskWrite = $state<ChartPoint[]>([]);
  let netSent = $state<ChartPoint[]>([]);
  let netRecv = $state<ChartPoint[]>([]);
  let sysCpu = $state<ChartPoint[]>([]);
  let sysMem = $state<ChartPoint[]>([]);

  const available = $derived(tickData?.available ?? false);
  const statusText = $derived(tickData?.status_text ?? 'Loading metrics...');
  const children = $derived<MetricsChildRow[]>(frame?.children_rows ?? []);
  const statusVariant = $derived(
    !available ? 'destructive' : !enabled ? 'outline' : pollError ? 'warning' : 'success'
  );

  function appendPoint(series: ChartPoint[], ts: number, value: number) {
    return [...series, { ts, value }].slice(-MAX_CHART_POINTS);
  }

  function applyFrame(nextFrame: MetricsUiFrame) {
    frame = nextFrame;
    const chart = nextFrame.chart;
    const ts = chart.ts_ms;
    if (procCpu.at(-1)?.ts === ts) return;

    procCpu = appendPoint(procCpu, ts, chart.proc_cpu);
    procRss = appendPoint(procRss, ts, chart.proc_rss_mb);
    procThreads = appendPoint(procThreads, ts, chart.proc_threads);
    diskRead = appendPoint(diskRead, ts, chart.disk_read_kb);
    diskWrite = appendPoint(diskWrite, ts, chart.disk_write_kb);
    netSent = appendPoint(netSent, ts, chart.net_sent_kb);
    netRecv = appendPoint(netRecv, ts, chart.net_recv_kb);
    sysCpu = appendPoint(sysCpu, ts, chart.sys_cpu);
    sysMem = appendPoint(sysMem, ts, chart.sys_mem_pct);
  }

  async function loadTick(syncControls = false) {
    if (polling) return;
    polling = true;
    try {
      const payload = await getMetricsTick();
      const data = payload.data;
      tickData = data;
      pollError = null;
      if (syncControls || !initialized) {
        enabled = data.enabled;
        intervalValue = data.interval;
      }
      if (data.frame) {
        applyFrame(data.frame);
      } else if (!data.enabled) {
        frame = null;
      }
    } catch (err) {
      pollError = err instanceof Error ? err.message : 'Metrics polling failed.';
    } finally {
      polling = false;
      loading = false;
      initialized = true;
    }
  }

  async function applyConfig(nextEnabled = enabled, nextInterval = intervalValue) {
    applying = true;
    error = null;
    try {
      const payload = await configureMetrics({
        enabled: nextEnabled,
        interval: nextInterval
      });
      enabled = payload.data.enabled;
      intervalValue = payload.data.interval;
      await loadTick(true);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to update metrics configuration.';
    } finally {
      applying = false;
    }
  }

  function onEnabledChange(event: Event) {
    enabled = (event.currentTarget as HTMLInputElement).checked;
    void applyConfig(enabled, intervalValue);
  }

  function onIntervalInput(event: Event) {
    intervalValue = Number((event.currentTarget as HTMLInputElement).value);
  }

  function onIntervalChange() {
    void applyConfig(enabled, intervalValue);
  }

  onMount(() => {
    void loadTick(true);
    const timer = window.setInterval(() => void loadTick(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  });
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Operations</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Metrics</h2>
    </div>

    <div class="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3">
      <label class="inline-flex items-center gap-2 font-sans text-sm font-semibold">
        <input
          class="size-4 accent-primary"
          type="checkbox"
          checked={enabled}
          disabled={!available || applying}
          onchange={onEnabledChange}
        />
        Enable metrics
      </label>
      <label class="flex min-w-60 items-center gap-3 font-sans text-sm text-muted-foreground">
        <span class="font-semibold text-foreground">Interval</span>
        <input
          class="min-w-36 flex-1 accent-primary"
          type="range"
          min="1"
          max="10"
          step="0.5"
          value={intervalValue}
          disabled={!available || applying}
          oninput={onIntervalInput}
          onchange={onIntervalChange}
        />
        <span class="w-12 text-right">{intervalValue.toFixed(1)}s</span>
      </label>
      <Button variant="outline" size="sm" disabled={polling} onclick={() => void loadTick(true)}>
        <RefreshCw size={15} class={cn(polling && 'animate-spin')} />
        Refresh
      </Button>
      <Badge variant={statusVariant}>{statusText}</Badge>
    </div>
  </div>

  {#if error || pollError}
    <div
      class={cn(
        'rounded-md border px-3 py-2 font-sans text-sm',
        error
          ? 'border-destructive/30 bg-destructive/10 text-destructive'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
      )}
    >
      {error ?? pollError}
    </div>
  {/if}

  {#if loading}
    <div class="grid min-h-80 place-items-center rounded-md border bg-card font-sans text-sm text-muted-foreground">
      Loading metrics...
    </div>
  {:else if !available}
    <div class="grid min-h-80 place-items-center rounded-md border bg-card p-6 text-center">
      <div>
        <Server class="mx-auto text-muted-foreground" size={34} />
        <h3 class="mt-3 font-sans text-lg font-semibold">Metrics collector is not available</h3>
      </div>
    </div>
  {:else}
    <div class="grid gap-4 lg:grid-cols-3">
      <article class="metric-card">
        <div class="metric-title">
          <Gauge size={19} />
          <h3>Process CPU</h3>
        </div>
        <strong>{frame?.process_cpu_label ?? '-'}</strong>
        <span>{frame?.process_pid_caption ?? '-'}</span>
        <Sparkline series={[{ label: 'cpu', color: 'var(--primary)', data: procCpu }]} yMax={100} />
      </article>

      <article class="metric-card">
        <div class="metric-title">
          <MemoryStick size={19} />
          <h3>Process Memory (RSS)</h3>
        </div>
        <strong>{frame?.process_rss_label ?? '-'}</strong>
        <span>{frame?.process_vms_caption ?? '-'}</span>
        <Sparkline series={[{ label: 'rss', color: 'var(--brand-green)', data: procRss }]} />
      </article>

      <article class="metric-card">
        <div class="metric-title">
          <Waypoints size={19} />
          <h3>Threads</h3>
        </div>
        <strong>{frame?.process_threads_label ?? '-'}</strong>
        <span>Server process</span>
        <Sparkline series={[{ label: 'threads', color: 'var(--brand)', data: procThreads }]} />
      </article>
    </div>

    <section class="grid gap-3">
      <h3 class="font-sans text-lg font-semibold text-muted-foreground">Channel Plugins</h3>
      <div class="overflow-hidden rounded-md border bg-card">
        <div class="grid min-w-[760px] grid-cols-[minmax(180px,1fr)_90px_100px_100px_110px_100px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
          <span>Channel</span>
          <span class="text-center">PID</span>
          <span class="text-center">Status</span>
          <span class="text-right">CPU %</span>
          <span class="text-right">RSS</span>
          <span class="text-right">Threads</span>
        </div>
        <div class="overflow-x-auto">
          {#each children as child (child.name)}
            <div class="grid min-w-[760px] grid-cols-[minmax(180px,1fr)_90px_100px_100px_110px_100px] gap-3 border-t px-3 py-2 font-sans text-sm">
              <span class="truncate font-semibold">{child.name}</span>
              <span class="text-center text-muted-foreground">{child.pid}</span>
              <span class="text-center">
                <Badge variant={child.alive === 'running' ? 'success' : 'outline'}>{child.alive}</Badge>
              </span>
              <span class="text-right">{child.cpu}</span>
              <span class="text-right">{child.rss}</span>
              <span class="text-right">{child.threads}</span>
            </div>
          {:else}
            <div class="border-t px-3 py-8 text-center font-sans text-sm text-muted-foreground">
              No channel plugin processes reported.
            </div>
          {/each}
        </div>
      </div>
      <p class="font-sans text-sm text-muted-foreground">{frame?.children_total_caption ?? '-'}</p>
    </section>

    <div class="grid gap-4 lg:grid-cols-2">
      <article class="metric-card">
        <div class="metric-title">
          <HardDrive size={19} />
          <h3>Disk Usage</h3>
        </div>
        <strong>{frame?.disk_percent_label ?? '-'}</strong>
        <span>{frame?.disk_detail_caption ?? '-'}</span>
        <span>{frame?.disk_rate_caption ?? '-'}</span>
        <Sparkline
          series={[
            { label: 'write', color: 'var(--brand-deep)', data: diskWrite },
            { label: 'read', color: 'var(--primary)', data: diskRead }
          ]}
        />
      </article>

      <article class="metric-card">
        <div class="metric-title">
          <Network size={19} />
          <h3>Network I/O</h3>
        </div>
        <strong>{frame?.net_total_rate_label ?? '-'}</strong>
        <span>{frame?.net_detail_caption ?? '-'}</span>
        <span>{frame?.net_packets_caption ?? '-'}</span>
        <Sparkline
          series={[
            { label: 'sent', color: 'var(--brand)', data: netSent },
            { label: 'recv', color: 'var(--brand-green)', data: netRecv }
          ]}
        />
      </article>
    </div>

    <details class="rounded-md border bg-card p-4">
      <summary class="cursor-pointer font-sans text-lg font-semibold text-muted-foreground">
        System-wide
      </summary>
      <div class="mt-4 grid gap-4 lg:grid-cols-2">
        <article class="metric-card metric-card--nested">
          <div class="metric-title">
            <Cpu size={19} />
            <h3>System CPU</h3>
          </div>
          <strong>{frame?.sys_cpu_label ?? '-'}</strong>
          <span>{frame?.sys_cpu_cores_caption ?? '-'}</span>
          <Sparkline series={[{ label: 'system-cpu', color: 'var(--primary)', data: sysCpu }]} yMax={100} />
        </article>

        <article class="metric-card metric-card--nested">
          <div class="metric-title">
            <Activity size={19} />
            <h3>System Memory</h3>
          </div>
          <strong>{frame?.sys_mem_label ?? '-'}</strong>
          <span>{frame?.sys_mem_detail_caption ?? '-'}</span>
          <Sparkline series={[{ label: 'system-memory', color: 'var(--brand-green)', data: sysMem }]} yMax={100} />
        </article>
      </div>
    </details>
  {/if}
</section>

<style>
  :global(.metric-card) {
    display: grid;
    gap: 0.65rem;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: var(--card);
    padding: 1rem;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
  }

  :global(.metric-card--nested) {
    background: color-mix(in srgb, var(--card) 85%, var(--background));
    box-shadow: none;
  }

  :global(.metric-title) {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.6rem;
    color: var(--muted-foreground);
  }

  :global(.metric-title h3) {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--foreground);
  }

  :global(.metric-card strong) {
    min-width: 0;
    overflow-wrap: anywhere;
    font-family: var(--font-sans);
    font-size: clamp(1.75rem, 4vw, 2.25rem);
    line-height: 1.05;
  }

  :global(.metric-card span) {
    min-width: 0;
    overflow-wrap: anywhere;
    font-family: var(--font-sans);
    font-size: 0.82rem;
    color: var(--muted-foreground);
  }
</style>
