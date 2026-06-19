import { describe, expect, it } from 'vitest';
import type { RetrievalTraceItem, RetrievalTraceStage } from '$lib/api/graph-runs';
import {
  ariaSortValue,
  buildLanes,
  findEmbedStage,
  hasItems,
  isExplicitBfsLeg,
  isRankStage,
  itemText,
  laneMatchCounts,
  legTag,
  provenance,
  rerankerLabel,
  resolveEffectiveSort,
  sortArrowGlyph,
  sortItems,
  sortValue,
  splitHighlight,
  stageHeadLabel,
  stageMatchCount,
  stageMetaSummary
} from './retrieval-trace-derive';

function item(p: Partial<RetrievalTraceItem> = {}): RetrievalTraceItem {
  return { uuid: 'u', score: null, ...p };
}

function stage(p: Partial<RetrievalTraceStage> = {}): RetrievalTraceStage {
  return { kind: 'candidate', label: 'Candidate', lane: 'edge', elapsed_ms: 0, meta: {}, items: [], ...p };
}

describe('legTag / rerankerLabel', () => {
  it('maps stage kind / method to a leg tag + class', () => {
    expect(legTag(stage({ kind: 'hop' }))).toEqual({ tag: 'hop', cls: 'hop' });
    expect(legTag(stage({ meta: { method: 'bm25' } }))).toEqual({ tag: 'BM25', cls: 'kw' });
    expect(legTag(stage({ meta: { method: 'cosine_similarity' } }))).toEqual({ tag: 'cosine', cls: 'mean' });
    expect(legTag(stage({ label: 'Custom', meta: {} }))).toEqual({ tag: 'Custom', cls: 'kw' });
  });

  it('prefers the reranker meta, else the second label segment', () => {
    expect(rerankerLabel(stage({ meta: { reranker: 'cohere' } }))).toBe('cohere');
    expect(rerankerLabel(stage({ label: 'Rerank · mxbai', meta: {} }))).toBe('mxbai');
    expect(rerankerLabel(stage({ label: 'Rerank', meta: {} }))).toBe('Rerank');
  });
});

describe('findEmbedStage / buildLanes', () => {
  const stages = [
    stage({ kind: 'embed', lane: 'query', label: 'Embed' }),
    stage({ kind: 'candidate', lane: 'edge', meta: { method: 'bm25' }, items: [item({ uuid: 'a' })] }),
    stage({ kind: 'hop', lane: 'edge', items: [item({ uuid: 'b' })] }),
    stage({ kind: 'rank', lane: 'edge', label: 'Rerank', items: [item({ uuid: 'a' }), item({ uuid: 'b' })] }),
    stage({ kind: 'temporal', lane: 'edge', items: [item({ uuid: 'a' })] }),
    stage({ kind: 'rank', lane: 'node', label: 'Rerank', items: [item({ uuid: 'n' })] })
  ];

  it('finds the shared embed stage', () => {
    expect(findEmbedStage(stages)?.kind).toBe('embed');
    expect(findEmbedStage([stage()])).toBeNull();
  });

  it('groups stages into lanes, skips embed, builds legs/flow/finalUuids', () => {
    const lanes = buildLanes(stages);
    expect(lanes.map((l) => l.lane)).toEqual(['edge', 'node']);
    const edge = lanes[0];
    // Legs come from candidate + hop stages only.
    expect(edge.legs.map((l) => l.tag)).toEqual(['BM25', 'hop']);
    // Flow funnel: two legs → rank → kept (final).
    expect(edge.flow.map((f) => f.emphasis)).toEqual(['leg', 'leg', 'rank', 'final']);
    // Final result = last stage (temporal) items.
    expect([...edge.finalUuids]).toEqual(['a']);
  });
});

describe('itemText / search', () => {
  it('joins lane-appropriate fields', () => {
    expect(itemText(item({ fact: 'A loves B', name: 'loves', uuid: 'x' }), 'edge')).toBe('A loves B loves x');
    expect(itemText(item({ name: 'Bob', entity_type: 'Person', summary: 's', uuid: 'x' }), 'node')).toBe(
      'Bob Person s x'
    );
    expect(itemText(item({ content: 'hi', source: 'msg', uuid: 'x' }), 'episode')).toBe('hi msg x');
  });

  it('splitHighlight marks matches case-insensitively, leaves non-matches whole', () => {
    expect(splitHighlight('Alice and alice', 'alice')).toEqual([
      { text: 'Alice', hit: true },
      { text: ' and ', hit: false },
      { text: 'alice', hit: true }
    ]);
    expect(splitHighlight('nothing', '')).toEqual([{ text: 'nothing', hit: false }]);
    expect(splitHighlight(null, 'x')).toEqual([{ text: '', hit: false }]);
  });

  it('counts distinct lane matches and per-stage matches', () => {
    const lanes = buildLanes([
      stage({ kind: 'candidate', lane: 'edge', items: [item({ uuid: 'a', fact: 'cat' }), item({ uuid: 'b', fact: 'dog' })] }),
      stage({ kind: 'rank', lane: 'edge', items: [item({ uuid: 'a', fact: 'cat' })] })
    ]);
    // 'cat' appears in uuid a across two stages → 1 distinct lane match.
    expect(laneMatchCounts(lanes, 'cat').get('edge')).toBe(1);
    expect(laneMatchCounts(lanes, '').size).toBe(0);
    expect(stageMatchCount(lanes[0].stages[0].stage, 'edge', 'cat')).toBe(1);
    expect(stageMatchCount(lanes[0].stages[0].stage, 'edge', '')).toBe(0);
  });
});

describe('stageHeadLabel / provenance / predicates / meta', () => {
  it('spells out the temporal lens, else uses the label', () => {
    expect(stageHeadLabel(stage({ kind: 'temporal' }))).toBe('Temporal lens (ordered by date)');
    expect(stageHeadLabel(stage({ label: 'Rerank', kind: 'rank' }))).toBe('Rerank');
  });

  it('provenance returns the legs whose uuid set contains the item', () => {
    const lane = buildLanes([
      stage({ kind: 'candidate', lane: 'edge', meta: { method: 'bm25' }, items: [item({ uuid: 'a' })] }),
      stage({ kind: 'rank', lane: 'edge', items: [item({ uuid: 'a' })] })
    ])[0];
    expect(provenance(item({ uuid: 'a' }), lane).map((l) => l.tag)).toEqual(['BM25']);
    expect(provenance(item({ uuid: 'z' }), lane)).toEqual([]);
  });

  it('isExplicitBfsLeg only for candidate+bfs', () => {
    expect(isExplicitBfsLeg(stage({ kind: 'candidate', meta: { method: 'bfs' } }))).toBe(true);
    expect(isExplicitBfsLeg(stage({ kind: 'hop', meta: { method: 'bfs' } }))).toBe(false);
  });

  it('isRankStage / hasItems', () => {
    expect(isRankStage(stage({ kind: 'rank' }))).toBe(true);
    expect(isRankStage(stage({ kind: 'candidate' }))).toBe(false);
    expect(hasItems(stage({ items: [item()] }))).toBe(true);
    expect(hasItems(stage({ items: [] }))).toBe(false);
  });

  it('stageMetaSummary joins non-empty meta + elapsed', () => {
    expect(stageMetaSummary(stage({ meta: { k: 5, skip: '', n: null }, elapsed_ms: 3.21 }))).toBe('k=5 · 3.2ms');
  });
});

describe('sort', () => {
  it('sortValue handles scores, validity, dates, strings, nulls', () => {
    expect(sortValue(item({ score: 0.5 }), 'score')).toBe(0.5);
    expect(sortValue(item({ score: null }), 'score')).toBe(Number.NEGATIVE_INFINITY);
    expect(sortValue(item({ invalid_at: 'x' }), 'v')).toBe(0);
    expect(sortValue(item({}), 'v')).toBe(1);
    expect(sortValue(item({ fact: 'ABC' }), 'fact')).toBe('abc');
    expect(sortValue(item({}), 'valid')).toBe('');
    expect(sortValue(item({ episodes: ['1', '2'] }), 'eps')).toBe(2);
  });

  it('sortItems returns original order without a sort, sorts a copy otherwise', () => {
    const items = [item({ uuid: 'a', score: 1 }), item({ uuid: 'b', score: 3 }), item({ uuid: 'c', score: 2 })];
    expect(sortItems(items, undefined)).toBe(items);
    const asc = sortItems(items, { key: 'score', dir: 1 });
    expect(asc.map((i) => i.uuid)).toEqual(['a', 'c', 'b']);
    expect(items.map((i) => i.uuid)).toEqual(['a', 'b', 'c']); // original untouched
    const desc = sortItems(items, { key: 'score', dir: -1 });
    expect(desc.map((i) => i.uuid)).toEqual(['b', 'c', 'a']);
  });

  it('resolveEffectiveSort defaults the temporal lens to valid-asc', () => {
    expect(resolveEffectiveSort(undefined, 'temporal')).toEqual({ key: 'valid', dir: 1 });
    expect(resolveEffectiveSort(undefined, 'rank')).toBeNull();
    expect(resolveEffectiveSort({ key: 'fact', dir: -1 }, 'temporal')).toEqual({ key: 'fact', dir: -1 });
  });

  it('sortArrowGlyph / ariaSortValue reflect the active column only', () => {
    expect(sortArrowGlyph({ key: 'fact', dir: 1 }, 'fact')).toBe('▲');
    expect(sortArrowGlyph({ key: 'fact', dir: -1 }, 'fact')).toBe('▼');
    expect(sortArrowGlyph({ key: 'fact', dir: 1 }, 'rel')).toBe('');
    expect(sortArrowGlyph(null, 'fact')).toBe('');
    expect(ariaSortValue({ key: 'fact', dir: 1 }, 'fact')).toBe('ascending');
    expect(ariaSortValue({ key: 'fact', dir: -1 }, 'fact')).toBe('descending');
    expect(ariaSortValue({ key: 'fact', dir: 1 }, 'rel')).toBe('none');
  });
});
