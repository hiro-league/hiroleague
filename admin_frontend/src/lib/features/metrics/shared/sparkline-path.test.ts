import { describe, expect, it } from 'vitest';
import { buildSparklinePaths, computeSparklineMaxValue } from './sparkline-path';

describe('computeSparklineMaxValue', () => {
  it('returns yMax when provided', () => {
    expect(
      computeSparklineMaxValue([{ label: 'a', color: 'red', data: [{ ts: 1, value: 99 }] }], 100)
    ).toBe(100);
  });

  it('returns at least 1 for empty values', () => {
    expect(computeSparklineMaxValue([{ label: 'a', color: 'red', data: [] }], null)).toBe(1);
  });

  it('uses the largest observed value across series', () => {
    expect(
      computeSparklineMaxValue(
        [
          { label: 'a', color: 'red', data: [{ ts: 1, value: 4 }] },
          { label: 'b', color: 'blue', data: [{ ts: 1, value: 9 }] }
        ],
        null
      )
    ).toBe(9);
  });
});

describe('buildSparklinePaths', () => {
  it('returns empty paths for empty data', () => {
    const [line] = buildSparklinePaths([{ label: 'cpu', color: 'red', data: [] }], null);
    expect(line.path).toBe('');
    expect(line.areaPath).toBe('');
  });

  it('builds a line and area path for two points', () => {
    const [line] = buildSparklinePaths(
      [
        {
          label: 'cpu',
          color: 'red',
          data: [
            { ts: 1, value: 0 },
            { ts: 2, value: 50 }
          ]
        }
      ],
      100
    );
    expect(line.path).toMatch(/^M 0 /);
    expect(line.path).toContain('L 100');
    expect(line.areaPath).toContain('Z');
  });

  it('clamps negative values to the baseline', () => {
    const [line] = buildSparklinePaths(
      [{ label: 'cpu', color: 'red', data: [{ ts: 1, value: -10 }] }],
      100
    );
    expect(line.path).toContain('M 0 32');
  });
});
