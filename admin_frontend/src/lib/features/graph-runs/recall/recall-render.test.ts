import { describe, expect, it } from 'vitest';
import type { RecalledFact } from '$lib/api/graph-runs';
import { episodeDate, recalledTabCount, sanitizeOneline, sentSet } from './recall-render';

describe('sanitizeOneline', () => {
  it('collapses whitespace, strips leading markdown and caps with an ellipsis', () => {
    expect(sanitizeOneline('  # a\n  b  ', 0)).toBe('a b');
    expect(sanitizeOneline('abcdefgh', 5)).toBe('abcd…');
  });
});

describe('sentSet', () => {
  it('keeps the top cap rows by score', () => {
    const rows: RecalledFact[] = [
      { memory: 'low', score: 0.1 },
      { memory: 'high', score: 0.9 },
      { memory: 'mid', score: 0.5 }
    ];
    const sent = sentSet(rows, 2);
    expect([...sent].map((r) => r.memory).sort()).toEqual(['high', 'mid']);
    expect(recalledTabCount(rows, 2, '')).toBe('2/3');
    expect(recalledTabCount(rows, 2, 'hi')).toBe('1/3');
  });
});

describe('episodeDate', () => {
  it('dashes empty and echoes an unreadable value', () => {
    expect(episodeDate('')).toBe('—');
    expect(episodeDate('weird')).toBe('weird');
  });
});
