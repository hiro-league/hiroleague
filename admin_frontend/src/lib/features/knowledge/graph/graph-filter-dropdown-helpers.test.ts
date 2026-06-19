import { describe, expect, it } from 'vitest';
import {
  filterDropdownPlaceholder,
  filterOptionsBySearch,
  filterSelectionSummary,
  sortFilterOptions,
  type GraphFilterOption
} from './graph-filter-dropdown-helpers';

const options: GraphFilterOption[] = [
  { value: 'a', label: 'Alice', weight: 3 },
  { value: 'b', label: 'Bob', weight: 10 },
  { value: 'c', label: 'Carol', weight: 1 }
];

describe('sortFilterOptions', () => {
  it('sorts by weight descending by default', () => {
    const sorted = sortFilterOptions(options, 'weight');
    expect(sorted.map((o) => o.value)).toEqual(['b', 'a', 'c']);
  });

  it('sorts alphabetically when requested', () => {
    const sorted = sortFilterOptions(options, 'alpha');
    expect(sorted.map((o) => o.label)).toEqual(['Alice', 'Bob', 'Carol']);
  });
});

describe('filterOptionsBySearch', () => {
  it('filters case-insensitively by label', () => {
    expect(filterOptionsBySearch(options, 'ali').map((o) => o.value)).toEqual(['a']);
    expect(filterOptionsBySearch(options, '')).toHaveLength(3);
  });
});

describe('filterSelectionSummary', () => {
  it('formats all, empty, and partial selections', () => {
    expect(filterSelectionSummary(5, 5)).toBe('all 5');
    expect(filterSelectionSummary(5, 0)).toBe('0/5');
    expect(filterSelectionSummary(5, 2)).toBe('2/5');
  });
});

describe('filterDropdownPlaceholder', () => {
  it('uses custom placeholder or derives from label', () => {
    expect(filterDropdownPlaceholder('Person')).toBe('Search Person…');
    expect(filterDropdownPlaceholder('Person', 'Find people…')).toBe('Find people…');
  });
});
