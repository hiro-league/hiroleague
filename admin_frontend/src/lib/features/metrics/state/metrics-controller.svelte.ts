import {
  configureMetrics,
  getMetricsTick,
  type MetricsChildRow,
  type MetricsTickResponse,
  type MetricsUiFrame
} from '$lib/api/metrics';
import type { Notify } from '$lib/ui/toast-types';
import { createPoller } from '$lib/state/create-poller.svelte';
import { appendMetricsChartPoint, type MetricsChartPoint } from '../shared/metrics-chart';
import {
  emptyMetricsChartSeries,
  METRICS_CHART_BINDINGS,
  type MetricsChartSeriesKey
} from '../shared/metrics-chart-series';

/** UI refresh cadence — independent of the server-side sample interval (`intervalValue`). */
const POLL_INTERVAL_MS = 2000;

export type MetricsController = ReturnType<typeof createMetricsController>;

export function createMetricsController(opts: { notify: Notify }) {
  const { notify } = opts;
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

  let chartSeries = $state<Record<MetricsChartSeriesKey, MetricsChartPoint[]>>(
    emptyMetricsChartSeries()
  );

  const available = $derived(tickData?.available ?? false);
  const statusText = $derived(tickData?.status_text ?? 'Loading metrics...');
  const children = $derived<MetricsChildRow[]>(frame?.children_rows ?? []);
  const statusVariant = $derived(
    !available ? 'destructive' : !enabled ? 'outline' : pollError ? 'warning' : 'success'
  );

  function clearChartSeries() {
    chartSeries = emptyMetricsChartSeries();
  }

  function chartSeriesFor(key: MetricsChartSeriesKey) {
    return chartSeries[key];
  }

  function applyFrame(nextFrame: MetricsUiFrame) {
    frame = nextFrame;
    const chart = nextFrame.chart;
    const ts = chart.ts_ms;
    if (chartSeries.procCpu.at(-1)?.ts === ts) return;

    const next = { ...chartSeries };
    for (const { stateKey, chartKey } of METRICS_CHART_BINDINGS) {
      next[stateKey] = appendMetricsChartPoint(next[stateKey], ts, chart[chartKey]);
    }
    chartSeries = next;
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
      } else {
        frame = null;
        clearChartSeries();
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
      const message =
        err instanceof Error ? err.message : 'Failed to update metrics configuration.';
      error = message;
      notify('error', message);
      // Resync toolbar controls from the server after optimistic checkbox/slider edits.
      await loadTick(true);
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

  const metricsPoller = createPoller(() => loadTick(), {
    intervalMs: POLL_INTERVAL_MS,
    immediate: true
  });

  function startPolling() {
    return metricsPoller.start();
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
    chartSeriesFor,
    loadTick,
    onEnabledChange,
    onIntervalInput,
    onIntervalChange,
    startPolling
  };
}
