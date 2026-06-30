import { describe, it, expect } from 'vitest';
import { buildEvalRunRequest, type BuildEvalRunRequestParams } from './eval-request';

const base = (over: Partial<BuildEvalRunRequestParams> = {}): BuildEvalRunRequestParams => ({
  track: 'memory',
  corpus: { id: 'c1', corpus_path: '/c1.json', questions_path: '/c1.q.yaml' },
  ingesting: false,
  judge: true,
  selectedIds: ['q1', 'q2'],
  buildGraph: false,
  selectedModes: ['flat', 'graphiti'],
  clearBefore: false,
  episodeFrom: 1,
  episodeTo: 0,
  questionConcurrency: 1,
  ...over
});

describe('buildEvalRunRequest — common fields', () => {
  it('carries corpus identity, judge, and ingest_synthetic from the intent', () => {
    const req = buildEvalRunRequest(base({ ingesting: true }));
    expect(req.corpus_id).toBe('c1');
    expect(req.corpus_path).toBe('/c1.json');
    expect(req.questions_path).toBe('/c1.q.yaml');
    expect(req.judge).toBe(true);
    expect(req.ingest_synthetic).toBe(true);
  });

  it('an ingest run sends NO questions; a questions run sends the selection', () => {
    expect(buildEvalRunRequest(base({ ingesting: true })).question_ids).toEqual([]);
    expect(buildEvalRunRequest(base({ ingesting: false })).question_ids).toEqual(['q1', 'q2']);
  });
});

describe('buildEvalRunRequest — knowledge track', () => {
  it('rebuilds the graph only on an ingest run and always sends the legs', () => {
    const ingest = buildEvalRunRequest(base({ track: 'knowledge', ingesting: true, buildGraph: true }));
    expect(ingest.build_graph).toBe(true);
    expect(ingest.modes).toEqual(['flat', 'graphiti']);
    const questions = buildEvalRunRequest(base({ track: 'knowledge', ingesting: false, buildGraph: true }));
    expect(questions.build_graph).toBe(false);
  });

  it('omits the memory-only fields', () => {
    const req = buildEvalRunRequest(base({ track: 'knowledge' }));
    expect(req.clear_before).toBeUndefined();
    expect(req.episode_offset).toBeUndefined();
    expect(req.episode_limit).toBeUndefined();
    expect(req.question_concurrency).toBeUndefined();
  });
});

describe('buildEvalRunRequest — memory track episode window', () => {
  it('converts 1-based inclusive from/to to 0-based offset + count', () => {
    const req = buildEvalRunRequest(base({ track: 'memory', episodeFrom: 5, episodeTo: 12 }));
    expect(req.episode_offset).toBe(4); // from - 1
    expect(req.episode_limit).toBe(8); // to - from + 1
  });

  it('episodeTo = 0 means "to the end" → null limit', () => {
    const req = buildEvalRunRequest(base({ track: 'memory', episodeFrom: 3, episodeTo: 0 }));
    expect(req.episode_offset).toBe(2);
    expect(req.episode_limit).toBeNull();
  });

  it('floors the offset at 0 (from = 1)', () => {
    expect(buildEvalRunRequest(base({ episodeFrom: 1, episodeTo: 1 })).episode_offset).toBe(0);
    expect(buildEvalRunRequest(base({ episodeFrom: 1, episodeTo: 1 })).episode_limit).toBe(1);
  });

  it('arms clear_before only on an ingest run', () => {
    expect(buildEvalRunRequest(base({ ingesting: true, clearBefore: true })).clear_before).toBe(true);
    expect(buildEvalRunRequest(base({ ingesting: false, clearBefore: true })).clear_before).toBe(false);
  });

  it('passes through the question concurrency cap', () => {
    const req = buildEvalRunRequest(base({ questionConcurrency: 4 }));
    expect(req.question_concurrency).toBe(4);
  });
});
