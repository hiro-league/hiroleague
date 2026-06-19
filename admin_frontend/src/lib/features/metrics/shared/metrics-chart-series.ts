import type { MetricsChartScalars } from '$lib/api/metrics';
import type { MetricsChartPoint } from './metrics-chart';

/** Client-side sparkline history keys owned by the metrics controller. */
export type MetricsChartSeriesKey =
  | 'procCpu'
  | 'procRss'
  | 'procThreads'
  | 'diskRead'
  | 'diskWrite'
  | 'netSent'
  | 'netRecv'
  | 'sysCpu'
  | 'sysMem';

type MetricsChartScalarKey = Exclude<keyof MetricsChartScalars, 'ts_ms'>;

export const METRICS_CHART_BINDINGS: ReadonlyArray<{
  stateKey: MetricsChartSeriesKey;
  chartKey: MetricsChartScalarKey;
}> = [
  { stateKey: 'procCpu', chartKey: 'proc_cpu' },
  { stateKey: 'procRss', chartKey: 'proc_rss_mb' },
  { stateKey: 'procThreads', chartKey: 'proc_threads' },
  { stateKey: 'diskRead', chartKey: 'disk_read_kb' },
  { stateKey: 'diskWrite', chartKey: 'disk_write_kb' },
  { stateKey: 'netSent', chartKey: 'net_sent_kb' },
  { stateKey: 'netRecv', chartKey: 'net_recv_kb' },
  { stateKey: 'sysCpu', chartKey: 'sys_cpu' },
  { stateKey: 'sysMem', chartKey: 'sys_mem_pct' }
];

export function emptyMetricsChartSeries(): Record<MetricsChartSeriesKey, MetricsChartPoint[]> {
  return {
    procCpu: [],
    procRss: [],
    procThreads: [],
    diskRead: [],
    diskWrite: [],
    netSent: [],
    netRecv: [],
    sysCpu: [],
    sysMem: []
  };
}
