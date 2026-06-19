import { describe, expect, it } from 'vitest';
import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/eval';
import {
  buildEpisodeNoMap,
  corpusScrollAnchorEpisodeId,
  filterCorpusEpisodes,
  isCorpusExtractionFilterActive
} from './eval-corpus-review-pure';

const episodes: EvalEpisode[] = [
  { id: 'e1', body: 'hello', speaker: 'A', timestamp: '2026-01-01T00:00:00Z', type: 'turn' },
  { id: 'e2', body: 'world', speaker: 'B', timestamp: '2026-01-02T00:00:00Z', type: 'turn' }
];

const extraction: Record<string, CorpusEpisodeExtraction> = {
  e1: { entity_count: 2, fact_count: 0, run_id: 'r1', step_index: 0 },
  e2: { entity_count: 0, fact_count: 0, run_id: 'r1', step_index: 1 }
};

describe('buildEpisodeNoMap', () => {
  it('assigns stable 1-based ordinals', () => {
    const m = buildEpisodeNoMap(episodes);
    expect(m.get('e1')).toBe(1);
    expect(m.get('e2')).toBe(2);
  });
});

describe('filterCorpusEpisodes', () => {
  it('filters by search term', () => {
    const out = filterCorpusEpisodes(
      episodes,
      'world',
      undefined,
      { noExtractionOnly: false, entRange: null, factRange: null, entActive: false, factActive: false },
      0,
      0
    );
    expect(out.map((e) => e.id)).toEqual(['e2']);
  });

  it('filters no-extraction episodes when enabled', () => {
    const state = {
      noExtractionOnly: true,
      entRange: null,
      factRange: null,
      entActive: false,
      factActive: false
    };
    expect(isCorpusExtractionFilterActive(state)).toBe(true);
    const out = filterCorpusEpisodes(episodes, '', extraction, state, 2, 0);
    expect(out.map((e) => e.id)).toEqual(['e2']);
  });
});

describe('corpusScrollAnchorEpisodeId', () => {
  it('picks the last episode whose top crossed the anchor line', () => {
    const nodes = new Map<string, HTMLElement>([
      ['e1', { getBoundingClientRect: () => ({ top: 40 }) } as HTMLElement],
      ['e2', { getBoundingClientRect: () => ({ top: 80 }) } as HTMLElement]
    ]);
    expect(corpusScrollAnchorEpisodeId(episodes, nodes, 50)).toBe('e1');
    expect(corpusScrollAnchorEpisodeId(episodes, nodes, 90)).toBe('e2');
  });

  it('stops at the first episode still below the anchor', () => {
    const nodes = new Map<string, HTMLElement>([
      ['e1', { getBoundingClientRect: () => ({ top: 10 }) } as HTMLElement],
      ['e2', { getBoundingClientRect: () => ({ top: 200 }) } as HTMLElement]
    ]);
    expect(corpusScrollAnchorEpisodeId(episodes, nodes, 50)).toBe('e1');
  });
});
