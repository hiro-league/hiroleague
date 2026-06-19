import { describe, expect, it } from 'vitest';
import type { EvalCorpus } from '$lib/api/eval';
import type { EvalCategoryStat } from '$lib/features/eval/shared/eval-events';
import {
  ingestState,
  orderedDifficulty,
  difficultyMeta,
  markVariant,
  markTitle,
  markLabel,
  evidenceVariant,
  deltaVariant,
  legLabel
} from './eval-display';

function corpus(p: Partial<EvalCorpus> = {}): EvalCorpus {
  return {
    id: 'c1',
    name: 'c1',
    corpus_path: '',
    questions_path: '',
    question_count: 0,
    item_count: 0,
    has_graph: false,
    ...p
  };
}

function stat(p: Partial<EvalCategoryStat> = {}): EvalCategoryStat {
  return { total: 0, groups: {}, correct: {}, score: {}, recall_ok: {}, ...p };
}

describe('ingestState', () => {
  it('is green + "fully ingested" when all episodes are in the graph', () => {
    expect(ingestState(corpus({ item_count: 10, ingested_count: 10 }))).toEqual({
      dot: '🟢',
      word: 'fully ingested'
    });
  });
  it('is yellow + "partially ingested" when some episodes are in', () => {
    expect(ingestState(corpus({ item_count: 10, ingested_count: 3 }))).toEqual({
      dot: '🟡',
      word: 'partially ingested'
    });
  });
  it('is white + "not ingested" when none are in and no graph', () => {
    expect(ingestState(corpus({ item_count: 10, ingested_count: 0, has_graph: false }))).toEqual({
      dot: '⚪',
      word: 'not ingested'
    });
  });
  it('falls back to green via has_graph when ranges were not recorded', () => {
    expect(ingestState(corpus({ item_count: 0, ingested_count: 0, has_graph: true }))).toEqual({
      dot: '🟢',
      word: 'fully ingested'
    });
  });
});

describe('orderedDifficulty', () => {
  it('reorders buckets into the medium→hard→very_hard ramp regardless of input order', () => {
    const input = { very_hard: stat(), medium: stat(), hard: stat() };
    expect(Object.keys(orderedDifficulty(input))).toEqual(['medium', 'hard', 'very_hard']);
  });
  it('sorts unknown buckets last', () => {
    const input = { mystery: stat(), medium: stat() };
    expect(Object.keys(orderedDifficulty(input))).toEqual(['medium', 'mystery']);
  });
});

describe('difficultyMeta', () => {
  it('maps known difficulties and returns null for unspecified/empty', () => {
    expect(difficultyMeta('medium')?.label).toBe('medium');
    expect(difficultyMeta('hard')?.label).toBe('hard');
    expect(difficultyMeta('very_hard')?.label).toBe('very hard');
    expect(difficultyMeta('')).toBeNull();
    expect(difficultyMeta('unspecified')).toBeNull();
  });
});

describe('verdict mark mappers', () => {
  it('markVariant colors each glyph (abstain is neutral)', () => {
    expect(markVariant('✓')).toBe('success');
    expect(markVariant('◐')).toBe('warning');
    expect(markVariant('✗')).toBe('destructive');
    expect(markVariant('🛇')).toBe('secondary');
    expect(markVariant('')).toBe('secondary');
  });
  it('markLabel gives a short word, "Not judged" when no glyph', () => {
    expect(markLabel('✓')).toBe('Pass');
    expect(markLabel('◐')).toBe('Partial');
    expect(markLabel('✗')).toBe('Fail');
    expect(markLabel('🛇')).toBe('Abstain');
    expect(markLabel('')).toBe('Not judged');
  });
  it('markTitle explains the glyph', () => {
    expect(markTitle('✓')).toContain('Pass');
    expect(markTitle('🛇')).toContain('Abstain');
    expect(markTitle('')).toBe('Not judged (judge was off)');
  });
});

describe('evidenceVariant', () => {
  it('grades coverage: none/secondary, all/success, some/warning, zero-matched/destructive', () => {
    expect(evidenceVariant(0, 0)).toBe('secondary');
    expect(evidenceVariant(3, 3)).toBe('success');
    expect(evidenceVariant(1, 3)).toBe('warning');
    expect(evidenceVariant(0, 3)).toBe('destructive');
  });
});

describe('deltaVariant', () => {
  it('greens a positive delta, warns a negative, neutral otherwise', () => {
    expect(deltaVariant('+1')).toBe('success');
    expect(deltaVariant('-2')).toBe('warning');
    expect(deltaVariant('0')).toBe('secondary');
  });
});

describe('legLabel', () => {
  it('uses the known leg labels and capitalizes unknown legs', () => {
    expect(legLabel('flat')).toBe('Flat');
    expect(legLabel('graphiti')).toBe('Graphiti');
    expect(legLabel('recall')).toBe('Recall');
  });
});
