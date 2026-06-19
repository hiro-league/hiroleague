import type { MetricsChartPoint } from './metrics-chart';

export const SPARKLINE_VIEW = {
  width: 100,
  height: 36,
  top: 3,
  bottom: 32
} as const;

export type SparklineInputSeries = {
  label: string;
  color: string;
  data: MetricsChartPoint[];
};

export type PreparedSparklineSeries = SparklineInputSeries & {
  path: string;
  areaPath: string;
};

export function computeSparklineMaxValue(
  series: readonly SparklineInputSeries[],
  yMax: number | null
): number {
  if (typeof yMax === 'number') return yMax;
  const values = series.flatMap((line) => line.data.map((point) => point.value));
  return Math.max(1, ...values);
}

export function buildSparklinePaths(
  series: readonly SparklineInputSeries[],
  yMax: number | null,
  view: Pick<typeof SPARKLINE_VIEW, 'width' | 'top' | 'bottom'> = SPARKLINE_VIEW
): PreparedSparklineSeries[] {
  const maxValue = computeSparklineMaxValue(series, yMax);
  const { width: viewWidth, top, bottom } = view;

  return series.map((line) => {
    const count = line.data.length;
    const coords = line.data.map((point, index) => {
      const x = count <= 1 ? 0 : (index / (count - 1)) * viewWidth;
      const y = bottom - (Math.max(0, point.value) / Math.max(maxValue, 1)) * (bottom - top);
      return [x, Math.max(top, Math.min(bottom, y))] as const;
    });
    const path = coords.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
    const first = coords[0];
    const last = coords[coords.length - 1];
    return {
      ...line,
      path,
      areaPath: first && last ? `${path} L ${last[0]} ${bottom} L ${first[0]} ${bottom} Z` : ''
    };
  });
}
