<script lang="ts">
  import {
    Activity,
    Cpu,
    Gauge,
    HardDrive,
    MemoryStick,
    Network,
    Server,
    Waypoints
  } from '@lucide/svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import MetricCard from '$lib/features/metrics/MetricCard.svelte';
  import Sparkline from '$lib/features/metrics/Sparkline.svelte';
  import type { MetricsController } from '$lib/features/metrics/state/metrics-controller.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { ADMIN_SECTION_HEADING_LG } from '$lib/styling/admin-tokens';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();

  const CHANNEL_GRID = 'minmax(180px,1fr) 90px 100px 100px 110px 100px';
</script>

{#if ctrl.error}
  <InlineDestructiveAlert message={ctrl.error} />
{:else if ctrl.pollError}
  <div
    class="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-sans text-sm text-amber-700 dark:text-amber-300"
  >
    {ctrl.pollError}
  </div>
{/if}

{#if ctrl.loading}
  <div class="grid min-h-80 place-items-center rounded-md border bg-card">
    <InlineLoading label="Loading metrics…" />
  </div>
{:else if !ctrl.available}
  <div class="grid min-h-80 place-items-center rounded-md border bg-card p-6 text-center">
    <div>
      <Server class="mx-auto text-muted-foreground" size={34} />
      <h3 class="mt-3 font-sans text-lg font-semibold">Metrics collector is not available</h3>
    </div>
  </div>
{:else}
  <div class="grid gap-4 lg:grid-cols-3">
    <MetricCard
      title="Process CPU"
      icon={Gauge}
      value={ctrl.frame?.process_cpu_label ?? '-'}
      caption={ctrl.frame?.process_pid_caption ?? '-'}
    >
      {#snippet children()}
        <Sparkline series={[{ label: 'cpu', color: 'var(--primary)', data: ctrl.procCpu }]} yMax={100} />
      {/snippet}
    </MetricCard>

    <MetricCard
      title="Process Memory (RSS)"
      icon={MemoryStick}
      value={ctrl.frame?.process_rss_label ?? '-'}
      caption={ctrl.frame?.process_vms_caption ?? '-'}
    >
      {#snippet children()}
        <Sparkline series={[{ label: 'rss', color: 'var(--brand-green)', data: ctrl.procRss }]} />
      {/snippet}
    </MetricCard>

    <MetricCard
      title="Threads"
      icon={Waypoints}
      value={ctrl.frame?.process_threads_label ?? '-'}
      caption="Server process"
    >
      {#snippet children()}
        <Sparkline series={[{ label: 'threads', color: 'var(--brand)', data: ctrl.procThreads }]} />
      {/snippet}
    </MetricCard>
  </div>

  <section class="grid gap-3">
    <h3 class={ADMIN_SECTION_HEADING_LG}>Channel Plugins</h3>
    {#if ctrl.children.length === 0}
      <div class="rounded-md border bg-card px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        No channel plugin processes reported.
      </div>
    {:else}
      <AdminTableShell layout="grid" minWidth={760} gridColumns={CHANNEL_GRID}>
        {#snippet headRow()}
          <span>Channel</span>
          <span class="text-center">PID</span>
          <span class="text-center">Status</span>
          <span class="text-right">CPU %</span>
          <span class="text-right">RSS</span>
          <span class="text-right">Threads</span>
        {/snippet}
        {#snippet body()}
          {#each ctrl.children as child (child.name)}
            <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={CHANNEL_GRID}>
              <span class="truncate font-semibold">{child.name}</span>
              <span class="text-center text-muted-foreground">{child.pid}</span>
              <span class="text-center">
                <Badge variant={child.alive === 'running' ? 'success' : 'outline'}>{child.alive}</Badge>
              </span>
              <span class="text-right">{child.cpu}</span>
              <span class="text-right">{child.rss}</span>
              <span class="text-right">{child.threads}</span>
            </div>
          {/each}
        {/snippet}
      </AdminTableShell>
    {/if}
    <p class="font-sans text-sm text-muted-foreground">{ctrl.frame?.children_total_caption ?? '-'}</p>
  </section>

  <div class="grid gap-4 lg:grid-cols-2">
    <MetricCard
      title="Disk Usage"
      icon={HardDrive}
      value={ctrl.frame?.disk_percent_label ?? '-'}
      caption={ctrl.frame?.disk_detail_caption ?? '-'}
      detail={ctrl.frame?.disk_rate_caption ?? '-'}
    >
      {#snippet children()}
        <Sparkline
          series={[
            { label: 'write', color: 'var(--brand-deep)', data: ctrl.diskWrite },
            { label: 'read', color: 'var(--primary)', data: ctrl.diskRead }
          ]}
        />
      {/snippet}
    </MetricCard>

    <MetricCard
      title="Network I/O"
      icon={Network}
      value={ctrl.frame?.net_total_rate_label ?? '-'}
      caption={ctrl.frame?.net_detail_caption ?? '-'}
      detail={ctrl.frame?.net_packets_caption ?? '-'}
    >
      {#snippet children()}
        <Sparkline
          series={[
            { label: 'sent', color: 'var(--brand)', data: ctrl.netSent },
            { label: 'recv', color: 'var(--brand-green)', data: ctrl.netRecv }
          ]}
        />
      {/snippet}
    </MetricCard>
  </div>

  <details class="rounded-md border bg-card p-4">
    <summary class="cursor-pointer font-sans text-lg font-semibold text-muted-foreground">
      System-wide
    </summary>
    <div class="mt-4 grid gap-4 lg:grid-cols-2">
      <MetricCard
        nested
        title="System CPU"
        icon={Cpu}
        value={ctrl.frame?.sys_cpu_label ?? '-'}
        caption={ctrl.frame?.sys_cpu_cores_caption ?? '-'}
      >
        {#snippet children()}
          <Sparkline
            series={[{ label: 'system-cpu', color: 'var(--primary)', data: ctrl.sysCpu }]}
            yMax={100}
          />
        {/snippet}
      </MetricCard>

      <MetricCard
        nested
        title="System Memory"
        icon={Activity}
        value={ctrl.frame?.sys_mem_label ?? '-'}
        caption={ctrl.frame?.sys_mem_detail_caption ?? '-'}
      >
        {#snippet children()}
          <Sparkline
            series={[{ label: 'system-memory', color: 'var(--brand-green)', data: ctrl.sysMem }]}
            yMax={100}
          />
        {/snippet}
      </MetricCard>
    </div>
  </details>
{/if}
