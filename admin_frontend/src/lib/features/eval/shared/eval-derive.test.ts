import { describe, expect, it } from 'vitest';
import type { EvalRow } from '$lib/features/eval/state/eval-model.svelte';
import type { EvalCategoryStat, EvalQuestionLeg } from '$lib/features/eval/shared/eval-events';
import {
  rowRecallRank,
  rowDiffRank,
  rowEvidenceRank,
  rowMarkRank,
  sortGroupRows,
  rowMatchesMark,
  rowMatchesFlag,
  rowHaystack,
  breakdownTotals
} from './eval-derive';

function leg(p: Partial<EvalQuestionLeg> = {}): EvalQuestionLeg {
  return { mark: '', elapsed_ms: 0, answer_preview: '', answer: '', run_id: null, ...p };
}

function row(p: Partial<EvalRow> = {}): EvalRow {
  return {
    index: 0,
    total: 1,
    id: 'q',
    category: 'cat',
    subcategory: '',
    difficulty: '',
    question: 'q?',
    requires_graph: false,
    track: 'memory',
    legs: {},
    delta: '0',
    gold: '',
    cost_usd: 0,
    is_negative_control: false,
    answered_at: '',
    evidence_recall: null,
    ...p
  };
}

function stat(p: Partial<EvalCategoryStat> = {}): EvalCategoryStat {
  return { total: 0, groups: {}, correct: {}, score: {}, recall_ok: {}, ...p };
}

describe('rowRecallRank', () => {
  it('miss=0, sufficient=1, unknown/not-judged=2', () => {
    expect(rowRecallRank(row({ legs: {} }))).toBe(2);
    expect(rowRecallRank(row({ legs: { recall: leg({ mark: '' }) } }))).toBe(2);
    expect(rowRecallRank(row({ legs: { recall: leg({ mark: '✗', recall_sufficient: false }) } }))).toBe(0);
    expect(rowRecallRank(row({ legs: { recall: leg({ mark: '✓', recall_sufficient: true }) } }))).toBe(1);
    // mark present but sufficiency unspecified ⇒ treated as sufficient (1)
    expect(rowRecallRank(row({ legs: { recall: leg({ mark: '✓' }) } }))).toBe(1);
  });
});

describe('rowDiffRank', () => {
  it('ramps medium<hard<very_hard, unknown last', () => {
    expect(rowDiffRank(row({ difficulty: 'medium' }))).toBe(0);
    expect(rowDiffRank(row({ difficulty: 'hard' }))).toBe(1);
    expect(rowDiffRank(row({ difficulty: 'very_hard' }))).toBe(2);
    expect(rowDiffRank(row({ difficulty: '' }))).toBe(3);
    expect(rowDiffRank(row({ difficulty: 'weird' }))).toBe(3);
  });
});

describe('rowEvidenceRank', () => {
  it('is the matched/total fraction, with no-evidence rows last (2)', () => {
    expect(rowEvidenceRank(row({ evidence_recall: null }))).toBe(2);
    expect(rowEvidenceRank(row({ evidence_recall: { matched: 0, total: 0, items: [] } }))).toBe(2);
    expect(rowEvidenceRank(row({ evidence_recall: { matched: 1, total: 2, items: [] } }))).toBe(0.5);
    expect(rowEvidenceRank(row({ evidence_recall: { matched: 3, total: 3, items: [] } }))).toBe(1);
  });
});

describe('rowMarkRank', () => {
  it('orders ✓<◐<✗<🛇<not-judged on the recall leg', () => {
    expect(rowMarkRank(row({ legs: { recall: leg({ mark: '✓' }) } }))).toBe(0);
    expect(rowMarkRank(row({ legs: { recall: leg({ mark: '◐' }) } }))).toBe(1);
    expect(rowMarkRank(row({ legs: { recall: leg({ mark: '✗' }) } }))).toBe(2);
    expect(rowMarkRank(row({ legs: { recall: leg({ mark: '🛇' }) } }))).toBe(3);
    expect(rowMarkRank(row({ legs: {} }))).toBe(4);
  });
  it('ranks a correct abstention as a pass (negative control)', () => {
    expect(
      rowMarkRank(row({ is_negative_control: true, legs: { recall: leg({ mark: '🛇' }) } }))
    ).toBe(0);
  });
});

describe('sortGroupRows', () => {
  const a = row({ index: 0, difficulty: 'very_hard', answered_at: '2026-06-11T10:00:00Z' });
  const b = row({ index: 1, difficulty: 'medium', answered_at: '2026-06-11T12:00:00Z' });
  const c = row({ index: 2, difficulty: 'hard', answered_at: '2026-06-11T08:00:00Z' });

  it('returns the input unchanged when sort is off', () => {
    const rows = [a, b, c];
    expect(sortGroupRows(rows, 'none', 'asc')).toBe(rows);
  });
  it('sorts ascending by difficulty rank', () => {
    expect(sortGroupRows([a, b, c], 'difficulty', 'asc').map((r) => r.index)).toEqual([1, 2, 0]);
  });
  it('reverses for descending', () => {
    expect(sortGroupRows([a, b, c], 'difficulty', 'desc').map((r) => r.index)).toEqual([0, 2, 1]);
  });
  it('sorts by time (answered_at) and is stable on index for ties', () => {
    expect(sortGroupRows([a, b, c], 'time', 'asc').map((r) => r.index)).toEqual([2, 0, 1]);
  });
  it('does not mutate the source array', () => {
    const rows = [a, b, c];
    sortGroupRows(rows, 'difficulty', 'asc');
    expect(rows.map((r) => r.index)).toEqual([0, 1, 2]);
  });
});

describe('rowMatchesMark', () => {
  it('matches "all", a specific verdict on any leg, and not-judged', () => {
    const r = row({ legs: { recall: leg({ mark: '✓' }) } });
    expect(rowMatchesMark(r, 'all')).toBe(true);
    expect(rowMatchesMark(r, 'pass')).toBe(true);
    expect(rowMatchesMark(r, 'fail')).toBe(false);
    expect(rowMatchesMark(row({ legs: { recall: leg({ mark: '' }) } }), 'not_judged')).toBe(true);
  });
  it('OR across knowledge legs', () => {
    const r = row({ legs: { flat: leg({ mark: '✗' }), graphiti: leg({ mark: '✓' }) } });
    expect(rowMatchesMark(r, 'pass')).toBe(true);
    expect(rowMatchesMark(r, 'fail')).toBe(true);
    expect(rowMatchesMark(r, 'partial')).toBe(false);
  });
  it('buckets a correct abstention under "pass", not "abstain"', () => {
    const r = row({ is_negative_control: true, legs: { recall: leg({ mark: '🛇' }) } });
    expect(rowMatchesMark(r, 'pass')).toBe(true);
    expect(rowMatchesMark(r, 'abstain')).toBe(false);
    expect(rowMatchesMark(r, 'incorrect')).toBe(false);
    // a plain abstain (not a negative control) still buckets under "abstain"
    const plain = row({ is_negative_control: false, legs: { recall: leg({ mark: '🛇' }) } });
    expect(rowMatchesMark(plain, 'abstain')).toBe(true);
    expect(rowMatchesMark(plain, 'pass')).toBe(false);
    expect(rowMatchesMark(plain, 'incorrect')).toBe(true);
  });

  it('matches incorrect as any leg that is not pass', () => {
    const pass = row({ legs: { recall: leg({ mark: '✓' }) } });
    const fail = row({ legs: { recall: leg({ mark: '✗' }) } });
    const partial = row({ legs: { recall: leg({ mark: '◐' }) } });
    const notJudged = row({ legs: { recall: leg({ mark: '' }) } });
    const mixed = row({ legs: { flat: leg({ mark: '✓' }), graphiti: leg({ mark: '✗' }) } });
    expect(rowMatchesMark(pass, 'incorrect')).toBe(false);
    expect(rowMatchesMark(fail, 'incorrect')).toBe(true);
    expect(rowMatchesMark(partial, 'incorrect')).toBe(true);
    expect(rowMatchesMark(notJudged, 'incorrect')).toBe(true);
    expect(rowMatchesMark(mixed, 'incorrect')).toBe(true);
  });
});

describe('rowMatchesFlag', () => {
  it('buckets miss/sufficient/unknown via the recall rank', () => {
    const miss = row({ legs: { recall: leg({ mark: '✗', recall_sufficient: false }) } });
    const ok = row({ legs: { recall: leg({ mark: '✓', recall_sufficient: true }) } });
    const unknown = row({ legs: {} });
    expect(rowMatchesFlag(miss, 'all')).toBe(true);
    expect(rowMatchesFlag(miss, 'miss')).toBe(true);
    expect(rowMatchesFlag(ok, 'sufficient')).toBe(true);
    expect(rowMatchesFlag(unknown, 'unknown')).toBe(true);
    expect(rowMatchesFlag(ok, 'miss')).toBe(false);
  });
});

describe('rowHaystack', () => {
  const r = row({
    question: 'Where does Adam work?',
    gold: 'Brightloom',
    legs: {
      recall: leg({
        mark: '✗',
        answer: 'I do not know.',
        reason: 'no spouse fact',
        recalled: [{ kind: 'fact', memory: 'Adam works at Brightloom', fact: 'WORKS_AT' }]
      })
    },
    evidence_recall: {
      matched: 0,
      total: 1,
      items: [
        { episode_id: 'ep1', short_id: 'e1', text: 'Adam joined Brightloom', matched: false, matched_via: '' }
      ]
    }
  });

  it('always includes the answer surface, lowercased', () => {
    const hay = rowHaystack(r, false);
    expect(hay).toContain('where does adam work?');
    expect(hay).toContain('i do not know.');
    expect(hay).toContain('fail'); // markLabel('✗')
    expect(hay).toContain('no spouse fact');
  });
  it('excludes recalled + evidence detail unless opted in', () => {
    const surface = rowHaystack(r, false);
    expect(surface).not.toContain('adam works at brightloom');
    expect(surface).not.toContain('adam joined brightloom');

    const deep = rowHaystack(r, true);
    expect(deep).toContain('adam works at brightloom');
    expect(deep).toContain('adam joined brightloom');
  });
});

describe('breakdownTotals', () => {
  it('sums per-bucket counts/scores/evidence across buckets for the given cols', () => {
    const bc: Record<string, EvalCategoryStat> = {
      direct: stat({
        total: 2,
        groups: { recall: { pass: 1, partial: 1, fail: 0, abstain: 0 } },
        correct: { recall: 1 },
        score: { recall: 1.5 },
        recall_ok: { recall: 2 },
        evidence_matched: 1,
        evidence_total: 2
      }),
      multi: stat({
        total: 3,
        groups: { recall: { pass: 2, partial: 0, fail: 1, abstain: 0 } },
        correct: { recall: 2 },
        score: { recall: 2 },
        recall_ok: { recall: 1 },
        evidence_matched: 2,
        evidence_total: 3
      })
    };
    const t = breakdownTotals(bc, ['recall']);
    expect(t.total).toBe(5);
    expect(t.groups.recall).toEqual({ pass: 3, partial: 1, fail: 1, abstain: 0 });
    expect(t.correct.recall).toBe(3);
    expect(t.score.recall).toBe(3.5);
    expect(t.recall_ok.recall).toBe(3);
    expect(t.evidence_matched).toBe(3);
    expect(t.evidence_total).toBe(5);
  });
});
