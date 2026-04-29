import { apiRequest, type ApiResponse } from './client';

export type MetricsChartScalars = {
  ts_ms: number;
  proc_cpu: number;
  proc_rss_mb: number;
  proc_threads: number;
  disk_read_kb: number;
  disk_write_kb: number;
  net_sent_kb: number;
  net_recv_kb: number;
  sys_cpu: number;
  sys_mem_pct: number;
};

export type MetricsChildRow = {
  name: string;
  pid: number;
  alive: string;
  cpu: string;
  rss: string;
  threads: number;
};

export type MetricsUiFrame = {
  chart: MetricsChartScalars;
  process_cpu_label: string;
  process_pid_caption: string;
  process_rss_label: string;
  process_vms_caption: string;
  process_threads_label: string;
  children_rows: MetricsChildRow[];
  children_total_caption: string;
  disk_percent_label: string;
  disk_detail_caption: string;
  disk_rate_caption: string;
  net_total_rate_label: string;
  net_detail_caption: string;
  net_packets_caption: string;
  sys_cpu_label: string;
  sys_cpu_cores_caption: string;
  sys_mem_label: string;
  sys_mem_detail_caption: string;
};

export type MetricsTickResponse = {
  available: boolean;
  enabled: boolean;
  interval: number;
  status_text: string;
  frame: MetricsUiFrame | null;
};

export type MetricsConfigState = {
  enabled: boolean;
  interval: number;
};

export function getMetricsTick(): Promise<ApiResponse<MetricsTickResponse>> {
  return apiRequest<MetricsTickResponse>('/metrics/tick');
}

export function configureMetrics(body: {
  enabled?: boolean | null;
  interval?: number | null;
}): Promise<ApiResponse<MetricsConfigState>> {
  return apiRequest<MetricsConfigState>('/metrics/configure', {
    method: 'POST',
    body
  });
}
