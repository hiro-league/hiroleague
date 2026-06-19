import { describe, expect, it } from 'vitest';
import {
  evalAnswerFilterOrAll,
  evalAnswerFiltersActive
} from './eval-answer-filters';

describe('evalAnswerFilterOrAll', () => {
  it('maps empty stored values to all', () => {
    expect(evalAnswerFilterOrAll('')).toBe('all');
    expect(evalAnswerFilterOrAll('  ')).toBe('all');
    expect(evalAnswerFilterOrAll('temporal')).toBe('temporal');
  });
});

describe('evalAnswerFiltersActive', () => {
  it('detects active filters', () => {
    const defaults = {
      ans_q: '',
      ans_rec: '',
      ans_cat: '',
      ans_diff: '',
      ans_flag: '',
      ans_mark: ''
    };
    expect(evalAnswerFiltersActive(defaults)).toBe(false);
    expect(evalAnswerFiltersActive({ ...defaults, ans_q: 'foo' })).toBe(true);
    expect(evalAnswerFiltersActive({ ...defaults, ans_rec: '1' })).toBe(true);
    expect(evalAnswerFiltersActive({ ...defaults, ans_mark: 'pass' })).toBe(true);
  });
});
