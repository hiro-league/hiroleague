import { describe, expect, it } from 'vitest';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import {
  buildPrefSearchIndex,
  countPrefMatchesByTab,
  filterPrefSearch,
  matchesPrefQuery,
  type PrefSearchEntry
} from './preferences-search-index';

const SAMPLE: PrefSearchEntry = {
  path: 'memory.search.top_k',
  title: 'Memories to recall (top K)',
  tabId: 'agent'
};

describe('preferences search index', () => {
  it('builds entries from the real schema, excluding read-only / image-lab fields', () => {
    const index = buildPrefSearchIndex(PREFERENCES_FIELD_SCHEMA);
    const paths = new Set(index.map((e) => e.path));
    expect(paths.has('llm.default_chat')).toBe(true);
    expect(paths.has('memory.search.top_k')).toBe(true);
    // read-only enrichment + image-lab-only fields are not searchable
    expect(paths.has('knowledge.answering.model_resolved')).toBe(false);
    expect(paths.has('image_profiles')).toBe(false);
    // every entry carries a non-empty title and a resolved tab
    expect(index.every((e) => e.title.length > 0 && e.tabId)).toBe(true);
  });

  it('matches case-insensitively by title or path, token-AND', () => {
    expect(matchesPrefQuery(SAMPLE, 'memories')).toBe(true);
    expect(matchesPrefQuery(SAMPLE, 'TOP k')).toBe(true); // both tokens present
    expect(matchesPrefQuery(SAMPLE, 'memory.search')).toBe(true); // path match
    expect(matchesPrefQuery(SAMPLE, 'top zzz')).toBe(false); // one token missing
    expect(matchesPrefQuery(SAMPLE, '')).toBe(false);
  });

  it('orders matches by tab, and counts per tab', () => {
    const index = buildPrefSearchIndex(PREFERENCES_FIELD_SCHEMA);
    const matches = filterPrefSearch(index, 'model');
    expect(matches.length).toBeGreaterThan(0);
    // sorted by tab order: models(0) ≤ agent(1) ≤ graph-engine(2) ≤ knowledge(3) ≤ eval(4)
    const order = ['models', 'agent', 'graph-engine', 'knowledge', 'eval', 'tuning-profiles'];
    const idxs = matches.map((m) => order.indexOf(m.tabId));
    expect(idxs).toEqual([...idxs].sort((a, b) => a - b));
    const counts = countPrefMatchesByTab(matches);
    const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
    expect(total).toBe(matches.length);
  });

  it('returns nothing for a blank query', () => {
    const index = buildPrefSearchIndex(PREFERENCES_FIELD_SCHEMA);
    expect(filterPrefSearch(index, '   ')).toEqual([]);
  });
});
