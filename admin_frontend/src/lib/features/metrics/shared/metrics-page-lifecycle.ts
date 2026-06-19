import type { MetricsController } from '../state/metrics-controller.svelte';

/** Initial tick + polling interval teardown for the Server metrics tab. */
export function setupMetricsTabRuntime(ctrl: MetricsController) {
  return ctrl.startPolling();
}
