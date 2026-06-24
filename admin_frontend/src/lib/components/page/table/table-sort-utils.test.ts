import { describe, expect, it } from 'vitest';
import { cycleTableSort, tableSortAria } from './table-sort-utils';

describe('cycleTableSort', () => {
  it('selects asc when switching to a new column', () => {
    expect(cycleTableSort('name', 'desc', 'status')).toEqual({
      sortBy: 'status',
      direction: 'asc'
    });
  });

  it('toggles asc to desc on the active column', () => {
    expect(cycleTableSort('name', 'asc', 'name')).toEqual({
      sortBy: 'name',
      direction: 'desc'
    });
  });

  it('toggles desc back to asc on the active column', () => {
    expect(cycleTableSort('name', 'desc', 'name')).toEqual({
      sortBy: 'name',
      direction: 'asc'
    });
  });

  it('threeState cycles asc → desc → none → asc on the same column', () => {
    expect(cycleTableSort('name', 'asc', 'name', { threeState: true })).toEqual({
      sortBy: 'name',
      direction: 'desc'
    });
    expect(cycleTableSort('name', 'desc', 'name', { threeState: true })).toEqual({
      sortBy: 'name',
      direction: 'none'
    });
    expect(cycleTableSort('name', 'none', 'name', { threeState: true })).toEqual({
      sortBy: 'name',
      direction: 'asc'
    });
  });
});

describe('tableSortAria', () => {
  it('returns none for inactive columns', () => {
    expect(tableSortAria('name', 'asc', 'status')).toBe('none');
  });

  it('returns none when direction is none', () => {
    expect(tableSortAria('name', 'none', 'name')).toBe('none');
  });

  it('maps asc and desc to aria-sort values', () => {
    expect(tableSortAria('name', 'asc', 'name')).toBe('ascending');
    expect(tableSortAria('name', 'desc', 'name')).toBe('descending');
  });
});
