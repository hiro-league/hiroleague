import type { MetricsUiFrame } from '$lib/api/metrics';

/** Read a preformatted string field from a metrics UI frame. */
export function frameString(
  frame: MetricsUiFrame | null,
  key?: keyof MetricsUiFrame,
  fallback = '-'
): string {
  if (!key || !frame) return fallback;
  const value = frame[key];
  return typeof value === 'string' ? value : fallback;
}
