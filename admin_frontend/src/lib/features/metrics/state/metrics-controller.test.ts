import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { MetricsUiFrame } from '$lib/api/metrics';

const h = vi.hoisted(() => ({
  tick: vi.fn(),
  configure: vi.fn()
}));

vi.mock('$lib/api/metrics', () => ({
  getMetricsTick: (...args: unknown[]) => h.tick(...(args as [])),
  configureMetrics: (...args: unknown[]) => h.configure(...(args as []))
}));

import { createMetricsController } from './metrics-controller.svelte';

function sampleFrame(ts = 1_000): MetricsUiFrame {
  return {
    chart: {
      ts_ms: ts,
      proc_cpu: 12.5,
      proc_rss_mb: 100,
      proc_threads: 8,
      disk_read_kb: 1,
      disk_write_kb: 2,
      net_sent_kb: 3,
      net_recv_kb: 4,
      sys_cpu: 45,
      sys_mem_pct: 50
    },
    process_cpu_label: '12.5%',
    process_pid_caption: 'PID 1',
    process_rss_label: '100 MB',
    process_vms_caption: 'VMS 200 MB',
    process_threads_label: '8',
    children_rows: [],
    children_total_caption: 'Total (server + 0 plugins): CPU 12.5%',
    disk_percent_label: '50%',
    disk_detail_caption: 'disk detail',
    disk_rate_caption: 'disk rate',
    net_total_rate_label: '7 kb/s',
    net_detail_caption: 'net detail',
    net_packets_caption: 'packets',
    sys_cpu_label: '45%',
    sys_cpu_cores_caption: 'C0: 45%',
    sys_mem_label: '50%',
    sys_mem_detail_caption: 'mem detail'
  };
}

function tickResponse(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      available: true,
      enabled: true,
      interval: 2,
      status_text: 'History: 1 samples',
      frame: sampleFrame(),
      ...overrides
    }
  };
}

function setup() {
  const notify = vi.fn();
  const ctrl = createMetricsController({ notify: (kind, message) => notify(kind, message) });
  return { ctrl, notify };
}

async function flushAsync() {
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  vi.clearAllMocks();
  h.tick.mockResolvedValue(tickResponse());
  h.configure.mockResolvedValue({ data: { enabled: true, interval: 2 } });
});

describe('createMetricsController — loadTick', () => {
  it('appends chart points from a frame', async () => {
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    expect(ctrl.chartSeriesFor('procCpu')).toEqual([{ ts: 1_000, value: 12.5 }]);
    expect(ctrl.loading).toBe(false);
  });

  it('dedupes ticks that share the same timestamp', async () => {
    h.tick.mockResolvedValue(tickResponse());
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    await ctrl.loadTick();
    expect(ctrl.chartSeriesFor('procCpu')).toHaveLength(1);
  });

  it('appends a new point when the timestamp advances', async () => {
    h.tick
      .mockResolvedValueOnce(tickResponse())
      .mockResolvedValueOnce(tickResponse({ frame: sampleFrame(2_000) }));
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    await ctrl.loadTick();
    expect(ctrl.chartSeriesFor('procCpu')).toEqual([
      { ts: 1_000, value: 12.5 },
      { ts: 2_000, value: 12.5 }
    ]);
  });

  it('clears chart history when the tick has no frame', async () => {
    h.tick
      .mockResolvedValueOnce(tickResponse())
      .mockResolvedValueOnce(tickResponse({ enabled: false, frame: null, status_text: 'Collection paused' }));
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    expect(ctrl.chartSeriesFor('procCpu')).toHaveLength(1);
    await ctrl.loadTick();
    expect(ctrl.chartSeriesFor('procCpu')).toEqual([]);
    expect(ctrl.frame).toBeNull();
  });

  it('records pollError when the tick request fails', async () => {
    h.tick.mockRejectedValueOnce(new Error('network down'));
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    expect(ctrl.pollError).toBe('network down');
  });
});

describe('createMetricsController — configure', () => {
  it('notifies and resyncs when configure fails', async () => {
    h.configure.mockRejectedValueOnce(new Error('configure failed'));
    h.tick
      .mockResolvedValueOnce(tickResponse({ interval: 2 }))
      .mockResolvedValueOnce(tickResponse({ interval: 4 }));
    const { ctrl, notify } = setup();
    await ctrl.loadTick(true);
    ctrl.onIntervalChange();
    await flushAsync();
    await flushAsync();
    expect(notify).toHaveBeenCalledWith('error', 'configure failed');
    expect(ctrl.error).toBe('configure failed');
    expect(h.tick).toHaveBeenCalledTimes(2);
    // After the failed configure, controls resync to the server's reported value.
    expect(ctrl.intervalValue).toBe(4);
  });
});

describe('createMetricsController — polling lifecycle', () => {
  it('startPolling returns an interval teardown function', () => {
    const clearInterval = vi.fn();
    const setInterval = vi.fn(() => 42);
    vi.stubGlobal('setInterval', setInterval);
    vi.stubGlobal('clearInterval', clearInterval);

    const { ctrl } = setup();
    const teardown = ctrl.startPolling();

    expect(typeof teardown).toBe('function');
    expect(setInterval).toHaveBeenCalled();
    teardown();
    expect(clearInterval).toHaveBeenCalledWith(42);

    vi.unstubAllGlobals();
  });

  it('chartSeriesFor returns the requested series snapshot', async () => {
    const { ctrl } = setup();
    await ctrl.loadTick(true);
    expect(ctrl.chartSeriesFor('procCpu')).toEqual([{ ts: 1_000, value: 12.5 }]);
  });
});
