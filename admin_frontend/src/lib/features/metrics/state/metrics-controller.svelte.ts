import {
  configureMetrics,
  getMetricsTick,
  type MetricsChildRow,
  type MetricsTickResponse,
  type MetricsUiFrame
} from '$lib/api/metrics';
import {
  appendMetricsChartPoint,
  type MetricsChartPoint
} from '../shared/metrics-chart';

const POLL_INTERVAL_MS = 2000;

export type MetricsController = ReturnType<typeof createMetricsController>;

export function createMetricsController() {
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

  let procCpu = $state<MetricsChartPoint[]>([]);
  let procRss = $state<MetricsChartPoint[]>([]);
  let procThreads = $state<MetricsChartPoint[]>([]);
  let diskRead = $state<MetricsChartPoint[]>([]);
  let diskWrite = $state<MetricsChartPoint[]>([]);
  let netSent = $state<MetricsChartPoint[]>([]);
  let netRecv = $state<MetricsChartPoint[]>([]);
  let sysCpu = $state<MetricsChartPoint[]>([]);
  let sysMem = $state<MetricsChartPoint[]>([]);

  const available = $derived(tickData?.available ?? false);
  const statusText = $derived(tickData?.status_text ?? 'Loading metrics...');
  const children = $derived<MetricsChildRow[]>(frame?.children_rows ?? []);
  const statusVariant = $derived(
    !available ? 'destructive' : !enabled ? 'outline' : pollError ? 'warning' : 'success'
  );

  function applyFrame(nextFrame: MetricsUiFrame) {
    frame = nextFrame;
    const chart = nextFrame.chart;
    const ts = chart.ts_ms;
    if (procCpu.at(-1)?.ts === ts) return;

    procCpu = appendMetricsChartPoint(procCpu, ts, chart.proc_cpu);
    procRss = appendMetricsChartPoint(procRss, ts, chart.proc_rss_mb);
    procThreads = appendMetricsChartPoint(procThreads, ts, chart.proc_threads);
    diskRead = appendMetricsChartPoint(diskRead, ts, chart.disk_read_kb);
    diskWrite = appendMetricsChartPoint(diskWrite, ts, chart.disk_write_kb);
    netSent = appendMetricsChartPoint(netSent, ts, chart.net_sent_kb);
    netRecv = appendMetricsChartPoint(netRecv, ts, chart.net_recv_kb);
    sysCpu = appendMetricsChartPoint(sysCpu, ts, chart.sys_cpu);
    sysMem = appendMetricsChartPoint(sysMem, ts, chart.sys_mem_pct);
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

  function startPolling() {
    void loadTick(true);
    const timer = window.setInterval(() => void loadTick(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }

  return {
    get tickData() {
      return tickData;
    },
    get frame() {
      return frame;
    },
    get enabled() {
      return enabled;
    },
    get intervalValue() {
      return intervalValue;
    },
    get loading() {
      return loading;
    },
    get applying() {
      return applying;
    },
    get error() {
      return error;
    },
    get pollError() {
      return pollError;
    },
    get polling() {
      return polling;
    },
    get available() {
      return available;
    },
    get statusText() {
      return statusText;
    },
    get statusVariant() {
      return statusVariant;
    },
    get children() {
      return children;
    },
    get procCpu() {
      return procCpu;
    },
    get procRss() {
      return procRss;
    },
    get procThreads() {
      return procThreads;
    },
    get diskRead() {
      return diskRead;
    },
    get diskWrite() {
      return diskWrite;
    },
    get netSent() {
      return netSent;
    },
    get netRecv() {
      return netRecv;
    },
    get sysCpu() {
      return sysCpu;
    },
    get sysMem() {
      return sysMem;
    },
    loadTick,
    onEnabledChange,
    onIntervalInput,
    onIntervalChange,
    startPolling
  };
}
