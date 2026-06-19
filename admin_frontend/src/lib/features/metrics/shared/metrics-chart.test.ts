import { describe, expect, it } from 'vitest';
import { appendMetricsChartPoint, METRICS_MAX_CHART_POINTS } from './metrics-chart';

describe('appendMetricsChartPoint', () => {
  it('appends a point to an empty series', () => {
    expect(appendMetricsChartPoint([], 100, 12.5)).toEqual([{ ts: 100, value: 12.5 }]);
  });

  it('keeps only the last maxPoints entries', () => {
    let series = appendMetricsChartPoint([], 1, 1);
    for (let i = 2; i <= METRICS_MAX_CHART_POINTS + 5; i += 1) {
      series = appendMetricsChartPoint(series, i, i);
    }
    expect(series).toHaveLength(METRICS_MAX_CHART_POINTS);
    expect(series.at(-1)).toEqual({ ts: METRICS_MAX_CHART_POINTS + 5, value: METRICS_MAX_CHART_POINTS + 5 });
    expect(series[0]?.ts).toBe(6);
  });

  it('honors a custom maxPoints cap', () => {
    const series = appendMetricsChartPoint(
      [
        { ts: 1, value: 1 },
        { ts: 2, value: 2 }
      ],
      3,
      3,
      2
    );
    expect(series).toEqual([
      { ts: 2, value: 2 },
      { ts: 3, value: 3 }
    ]);
  });
});
