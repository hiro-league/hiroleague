import { describe, expect, it } from 'vitest';
import { distinctOptionsWithSentinel, DISTINCT_EMPTY_VALUE } from './distinct-options';

describe('distinctOptionsWithSentinel', () => {
  it('returns sorted distinct values', () => {
    expect(
      distinctOptionsWithSentinel(
        [{ s: 'beta' }, { s: 'alpha' }, { s: 'beta' }],
        (r) => r.s
      )
    ).toEqual([
      { value: 'alpha', label: 'alpha' },
      { value: 'beta', label: 'beta' }
    ]);
  });

  it('prepends a sentinel when any row is empty', () => {
    expect(
      distinctOptionsWithSentinel([{ s: 'ok' }, { s: '' }, { s: 'ok' }], (r) => r.s, {
        emptyLabel: '(no status)'
      })
    ).toEqual([
      { value: DISTINCT_EMPTY_VALUE, label: '(no status)' },
      { value: 'ok', label: 'ok' }
    ]);
  });

  it('can preserve first-seen order when sort is false', () => {
    expect(
      distinctOptionsWithSentinel([{ c: 'b' }, { c: 'a' }, { c: 'b' }], (r) => r.c, {
        sort: false
      })
    ).toEqual([{ value: 'b', label: 'b' }, { value: 'a', label: 'a' }]);
  });
});
