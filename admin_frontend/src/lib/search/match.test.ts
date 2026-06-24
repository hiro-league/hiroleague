import { describe, expect, it } from 'vitest';
import { splitOnQuery, matchesQuery, rowMatches } from './match';

describe('splitOnQuery', () => {
  it('returns one non-hit segment when the query is blank or whitespace-only', () => {
    expect(splitOnQuery('hello', '')).toEqual([{ text: 'hello', hit: false }]);
    expect(splitOnQuery('hello', '   ')).toEqual([{ text: 'hello', hit: false }]);
  });

  it('returns one non-hit segment for null, undefined, or empty text', () => {
    expect(splitOnQuery(null, 'x')).toEqual([{ text: '', hit: false }]);
    expect(splitOnQuery(undefined, 'x')).toEqual([{ text: '', hit: false }]);
    expect(splitOnQuery('', 'x')).toEqual([{ text: '', hit: false }]);
  });

  it('marks matches case-insensitively', () => {
    expect(splitOnQuery('Alice and alice', 'alice')).toEqual([
      { text: 'Alice', hit: true },
      { text: ' and ', hit: false },
      { text: 'alice', hit: true }
    ]);
  });

  it('splits multiple hits in one string', () => {
    expect(splitOnQuery('cat catapult cat', 'cat')).toEqual([
      { text: 'cat', hit: true },
      { text: ' ', hit: false },
      { text: 'cat', hit: true },
      { text: 'apult ', hit: false },
      { text: 'cat', hit: true }
    ]);
  });

  it('returns the whole string as non-hit when nothing matches', () => {
    expect(splitOnQuery('nothing here', 'xyz')).toEqual([{ text: 'nothing here', hit: false }]);
  });
});

describe('matchesQuery', () => {
  it('is case-insensitive and false for blank query', () => {
    expect(matchesQuery('Foo Bar', 'bar')).toBe(true);
    expect(matchesQuery('Foo Bar', '   ')).toBe(false);
    expect(matchesQuery('Foo Bar', '')).toBe(false);
  });
});

describe('rowMatches', () => {
  it('matches when any field hits and false for blank query', () => {
    const row = { title: 'Hello', subtitle: 'World' };
    expect(rowMatches(row, 'hello', (r) => [r.title, r.subtitle])).toBe(true);
    expect(rowMatches(row, 'world', (r) => [r.title, r.subtitle])).toBe(true);
    expect(rowMatches(row, 'xyz', (r) => [r.title, r.subtitle])).toBe(false);
    expect(rowMatches(row, '   ', (r) => [r.title, r.subtitle])).toBe(false);
  });
});
