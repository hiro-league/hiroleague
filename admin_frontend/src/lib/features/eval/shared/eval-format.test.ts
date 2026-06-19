import { describe, expect, it } from 'vitest';
import {
  fmtCost,
  fmtScore,
  pct,
  fmtTime,
  fmtDateTime,
  timeMs,
  fmtEpisodeDate
} from './eval-format';

describe('fmtCost', () => {
  it('renders non-positive / invalid as "$0.00"', () => {
    expect(fmtCost(0)).toBe('$0.00');
    expect(fmtCost(-1)).toBe('$0.00');
    expect(fmtCost(null)).toBe('$0.00');
    expect(fmtCost(undefined)).toBe('$0.00');
    expect(fmtCost(Number.NaN)).toBe('$0.00');
  });
  it('uses 4dp under a cent, 2dp at/above', () => {
    expect(fmtCost(0.0042)).toBe('$0.0042');
    expect(fmtCost(0.01)).toBe('$0.01');
    expect(fmtCost(12.5)).toBe('$12.50');
  });
});

describe('fmtScore', () => {
  it('shows a decimal only when fractional', () => {
    expect(fmtScore(13)).toBe('13');
    expect(fmtScore(12.5)).toBe('12.5');
    expect(fmtScore(0)).toBe('0');
  });
});

describe('pct', () => {
  it('returns "—" when total is 0 / falsy', () => {
    expect(pct(0, 0)).toBe('—');
    expect(pct(5, 0)).toBe('—');
  });
  it('renders a whole-number percentage WITH the % sign', () => {
    expect(pct(85, 100)).toBe('85%');
    expect(pct(1, 3)).toBe('33%');
    expect(pct(2, 3)).toBe('67%');
  });
});

describe('time helpers', () => {
  const iso = '2026-06-11T16:35:00Z';
  it('fmtTime: dash for empty/invalid, a clock string otherwise', () => {
    expect(fmtTime('')).toBe('—');
    expect(fmtTime(undefined)).toBe('—');
    expect(fmtTime('not-a-date')).toBe('—');
    expect(fmtTime(iso)).not.toBe('—');
  });
  it('fmtDateTime: "Not run yet" for empty, echoes an unparseable string, formats a valid one', () => {
    expect(fmtDateTime(undefined)).toBe('Not run yet');
    expect(fmtDateTime('')).toBe('Not run yet');
    expect(fmtDateTime('nope')).toBe('nope');
    expect(fmtDateTime(iso)).not.toBe('Not run yet');
  });
  it('timeMs: 0 for empty/invalid, epoch ms for a valid ISO', () => {
    expect(timeMs(undefined)).toBe(0);
    expect(timeMs('nope')).toBe(0);
    expect(timeMs(iso)).toBe(Date.parse(iso));
  });
  it('fmtEpisodeDate: UTC date slice (timezone-stable), echo invalid, dash empty', () => {
    expect(fmtEpisodeDate('')).toBe('—');
    expect(fmtEpisodeDate('weird')).toBe('weird');
    expect(fmtEpisodeDate(iso)).toBe('2026-06-11');
  });
});
