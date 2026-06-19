import type { Component } from 'svelte';
import {
  Activity,
  Cpu,
  Gauge,
  HardDrive,
  MemoryStick,
  Network,
  Waypoints
} from '@lucide/svelte';
import type { MetricsUiFrame } from '$lib/api/metrics';
import type { MetricsChartSeriesKey } from './metrics-chart-series';

export type MetricsSparklineSpec = {
  label: string;
  color: string;
  seriesKey: MetricsChartSeriesKey;
};

export type MetricsCardSpec = {
  id: string;
  title: string;
  icon: Component<{ size?: number }>;
  valueKey?: keyof MetricsUiFrame;
  captionKey?: keyof MetricsUiFrame;
  detailKey?: keyof MetricsUiFrame;
  /** Used when the caption is not sourced from the API frame. */
  staticCaption?: string;
  nested?: boolean;
  yMax?: number;
  sparklines: readonly MetricsSparklineSpec[];
};

export const METRICS_PROCESS_CARDS: readonly MetricsCardSpec[] = [
  {
    id: 'process-cpu',
    title: 'Process CPU',
    icon: Gauge,
    valueKey: 'process_cpu_label',
    captionKey: 'process_pid_caption',
    yMax: 100,
    sparklines: [{ label: 'cpu', color: 'var(--primary)', seriesKey: 'procCpu' }]
  },
  {
    id: 'process-rss',
    title: 'Process Memory (RSS)',
    icon: MemoryStick,
    valueKey: 'process_rss_label',
    captionKey: 'process_vms_caption',
    sparklines: [{ label: 'rss', color: 'var(--brand-green)', seriesKey: 'procRss' }]
  },
  {
    id: 'process-threads',
    title: 'Threads',
    icon: Waypoints,
    valueKey: 'process_threads_label',
    staticCaption: 'Server process',
    sparklines: [{ label: 'threads', color: 'var(--brand)', seriesKey: 'procThreads' }]
  }
];

export const METRICS_IO_CARDS: readonly MetricsCardSpec[] = [
  {
    id: 'disk-usage',
    title: 'Disk Usage',
    icon: HardDrive,
    valueKey: 'disk_percent_label',
    captionKey: 'disk_detail_caption',
    detailKey: 'disk_rate_caption',
    sparklines: [
      { label: 'write', color: 'var(--brand-deep)', seriesKey: 'diskWrite' },
      { label: 'read', color: 'var(--primary)', seriesKey: 'diskRead' }
    ]
  },
  {
    id: 'network-io',
    title: 'Network I/O',
    icon: Network,
    valueKey: 'net_total_rate_label',
    captionKey: 'net_detail_caption',
    detailKey: 'net_packets_caption',
    sparklines: [
      { label: 'sent', color: 'var(--brand)', seriesKey: 'netSent' },
      { label: 'recv', color: 'var(--brand-green)', seriesKey: 'netRecv' }
    ]
  }
];

export const METRICS_SYSTEM_CARDS: readonly MetricsCardSpec[] = [
  {
    id: 'system-cpu',
    title: 'System CPU',
    icon: Cpu,
    valueKey: 'sys_cpu_label',
    captionKey: 'sys_cpu_cores_caption',
    nested: true,
    yMax: 100,
    sparklines: [{ label: 'system-cpu', color: 'var(--primary)', seriesKey: 'sysCpu' }]
  },
  {
    id: 'system-memory',
    title: 'System Memory',
    icon: Activity,
    valueKey: 'sys_mem_label',
    captionKey: 'sys_mem_detail_caption',
    nested: true,
    yMax: 100,
    sparklines: [{ label: 'system-memory', color: 'var(--brand-green)', seriesKey: 'sysMem' }]
  }
];
