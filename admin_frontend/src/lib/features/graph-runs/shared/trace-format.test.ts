import { describe, expect, it } from 'vitest';
import {
  cell,
  episodeSourceLabel,
  fmtDate,
  formatScore,
  isCurrent,
  isISO,
  isPlainObject,
  prettyKey,
  shortDate,
  temporalTitle
} from './trace-format';

describe('isCurrent', () => {
  it('is current when neither end is set', () => {
    expect(isCurrent({})).toBe(true);
    expect(isCurrent({ valid_at: '2020-01-01' })).toBe(true);
  });

  it('is superseded when invalid_at or expired_at is set', () => {
    expect(isCurrent({ invalid_at: '2020-01-01' })).toBe(false);
    expect(isCurrent({ expired_at: '2020-01-01' })).toBe(false);
  });

  it('treats null/undefined ends as current', () => {
    expect(isCurrent({ invalid_at: null, expired_at: null })).toBe(true);
  });
});

describe('temporalTitle', () => {
  it('lists each bound that is present', () => {
    expect(temporalTitle({ valid_at: 'a', invalid_at: 'b', expired_at: 'c' })).toBe(
      'became true: a\nstopped being true: b\nsystem-expired: c'
    );
  });

  it('falls back to a no-bounds message', () => {
    expect(temporalTitle({})).toBe('no temporal bounds');
  });
});

describe('fmtDate', () => {
  it('formats far-future microsecond ISO timestamps (Date would choke)', () => {
    expect(fmtDate('2213-11-30T08:00:00.000000Z')).toBe('30 Nov 2213, 08:00 UTC');
  });

  it('drops the time when withTime is false', () => {
    expect(fmtDate('2213-11-30T08:00:00.000000Z', false)).toBe('30 Nov 2213');
  });

  it('handles a date-only value', () => {
    expect(fmtDate('1999-01-05')).toBe('5 Jan 1999');
  });

  it('returns the raw string when unparseable, and empty for nullish', () => {
    expect(fmtDate('not-a-date')).toBe('not-a-date');
    expect(fmtDate('')).toBe('');
    expect(fmtDate(null)).toBe('');
    expect(fmtDate(undefined)).toBe('');
  });
});

describe('isISO', () => {
  it('matches ISO-shaped strings only', () => {
    expect(isISO('2024-06-19')).toBe(true);
    expect(isISO('2024-06-19T08:00')).toBe(true);
    expect(isISO('hello')).toBe(false);
    expect(isISO(42)).toBe(false);
    expect(isISO(null)).toBe(false);
  });
});

describe('shortDate', () => {
  it('slices to YYYY-MM-DD, empty for nullish', () => {
    expect(shortDate('2213-11-30T08:00:00.000000Z')).toBe('2213-11-30');
    expect(shortDate(null)).toBe('');
    expect(shortDate(undefined)).toBe('');
  });
});

describe('cell', () => {
  it('renders scalars verbatim and dashes empties', () => {
    expect(cell('hi')).toBe('hi');
    expect(cell(0)).toBe('0');
    expect(cell(false)).toBe('false');
    expect(cell('')).toBe('—');
    expect(cell(null)).toBe('—');
    expect(cell(undefined)).toBe('—');
  });

  it('serializes nested structures as compact JSON', () => {
    expect(cell({ a: 1 })).toBe('{"a":1}');
    expect(cell([1, 2])).toBe('[1,2]');
  });
});

describe('prettyKey', () => {
  it('replaces underscores with spaces', () => {
    expect(prettyKey('entity_type_id')).toBe('entity type id');
  });
});

describe('isPlainObject', () => {
  it('is true for plain objects only', () => {
    expect(isPlainObject({})).toBe(true);
    expect(isPlainObject([])).toBe(false);
    expect(isPlainObject(null)).toBe(false);
    expect(isPlainObject('x')).toBe(false);
  });
});

describe('formatScore', () => {
  it('fixes to 4 decimals, dashes nullish', () => {
    expect(formatScore(0.12345)).toBe('0.1235');
    expect(formatScore(0)).toBe('0.0000');
    expect(formatScore(null)).toBe('—');
    expect(formatScore(undefined)).toBe('—');
  });
});

describe('episodeSourceLabel', () => {
  it('strips the EpisodeType. prefix and dashes empties', () => {
    expect(episodeSourceLabel('EpisodeType.message')).toBe('message');
    expect(episodeSourceLabel('json')).toBe('json');
    expect(episodeSourceLabel('')).toBe('—');
    expect(episodeSourceLabel(null)).toBe('—');
  });
});
