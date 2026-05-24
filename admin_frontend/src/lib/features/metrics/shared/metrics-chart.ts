export type MetricsChartPoint = {
  ts: number;
  value: number;
};

export const METRICS_MAX_CHART_POINTS = 60;

export function appendMetricsChartPoint(
  series: MetricsChartPoint[],
  ts: number,
  value: number,
  maxPoints = METRICS_MAX_CHART_POINTS
): MetricsChartPoint[] {
  return [...series, { ts, value }].slice(-maxPoints);
}
