import { describe, it, expect } from 'vitest';
import { listBenchmarks, visibleCorpusesFor } from './eval-corpus';
import type { EvalCorpus } from '$lib/api/knowledge';

const corpus = (over: Partial<EvalCorpus> = {}): EvalCorpus => ({
  id: 'c',
  name: 'c',
  corpus_path: '/c',
  questions_path: '/c.q',
  question_count: 0,
  item_count: 0,
  has_graph: false,
  ...over
});

describe('listBenchmarks', () => {
  it('returns distinct benchmarks in first-seen order', () => {
    const out = listBenchmarks([
      corpus({ id: 'a', benchmark: 'beam', benchmark_label: 'BEAM' }),
      corpus({ id: 'b', benchmark: 'locomo', benchmark_label: 'LoCoMo' }),
      corpus({ id: 'c', benchmark: 'beam', benchmark_label: 'BEAM' })
    ]);
    expect(out).toEqual([
      { id: 'beam', label: 'BEAM' },
      { id: 'locomo', label: 'LoCoMo' }
    ]);
  });

  it('falls back to the id when no label is set', () => {
    expect(listBenchmarks([corpus({ benchmark: 'locomo' })])).toEqual([
      { id: 'locomo', label: 'locomo' }
    ]);
  });

  it('is empty when no corpus carries a benchmark (knowledge track)', () => {
    expect(listBenchmarks([corpus({ id: 'a' }), corpus({ id: 'b' })])).toEqual([]);
  });
});

describe('visibleCorpusesFor', () => {
  const list = [
    corpus({ id: 'a', benchmark: 'beam' }),
    corpus({ id: 'b', benchmark: 'locomo' }),
    corpus({ id: 'c', benchmark: 'beam' })
  ];

  it('filters to the given benchmark', () => {
    expect(visibleCorpusesFor(list, 'beam').map((c) => c.id)).toEqual(['a', 'c']);
  });

  it('returns the full flat list when no benchmark is set', () => {
    expect(visibleCorpusesFor(list, '').map((c) => c.id)).toEqual(['a', 'b', 'c']);
  });
});
