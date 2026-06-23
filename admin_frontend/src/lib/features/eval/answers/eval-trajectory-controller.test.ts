import { describe, expect, it } from 'vitest';
import type { EvalQuestionLeg } from '$lib/features/eval/shared/eval-events';
import type { EvalRow } from '$lib/features/eval/shared/eval-row';
import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';
import {
  decompositionRate,
  recallCellLabel,
  recallFoldLabel,
  recallLoopSaturated,
  turnsPerQuestionHistogram,
  trajectoryPaneSnapshot,
  trajectoryStats
} from './eval-trajectory-controller.svelte';

function sub(sid: number, overrides: Partial<RetrievalLoop['turns'][0]['sub_queries'][0]> = {}) {
  return {
    sid,
    goal: `goal-${sid}`,
    query: `q-${sid}`,
    temporal: 'current' as const,
    limit: 20,
    hops: 1 as const,
    show_expiry: false,
    returned: 4,
    new: 2,
    accumulated_total: sid * 2,
    ...overrides
  };
}

function loop(overrides: Partial<RetrievalLoop> = {}): RetrievalLoop {
  return {
    turns: [{ turn: 1, sub_queries: [sub(1)] }],
    agent_turns: 2,
    max_agent_turns: 4,
    stopped_reason: 'model_answered',
    ...overrides
  };
}

function row(leg: Partial<EvalQuestionLeg>): EvalRow {
  return {
    index: 0,
    total: 1,
    id: 'q1',
    category: '',
    subcategory: '',
    difficulty: '',
    question: 'Q?',
    requires_graph: false,
    track: 'memory',
    legs: { recall: { mark: '', elapsed_ms: 0, answer_preview: '', answer: '', run_id: null, ...leg } },
    delta: '0',
    gold: '',
    cost_usd: 0,
    is_negative_control: false,
    answered_at: '',
    evidence_recall: null,
    rubric: []
  };
}

describe('trajectoryStats', () => {
  it('builds footer stats', () => {
    const stats = trajectoryStats(loop(), 3);
    expect(stats.totalLabel).toBe('2 of 4');
    expect(stats.accumulatedLabel).toBe('3 items');
  });
});

describe('recallCellLabel / saturation', () => {
  it('falls back to flat fact count without loop', () => {
    const leg: EvalQuestionLeg = {
      mark: '',
      elapsed_ms: 0,
      answer_preview: '',
      answer: '',
      run_id: null,
      recalled: [{ memory: 'a' }, { memory: 'b' }]
    };
    expect(recallCellLabel(leg)).toBe('2');
  });

  it('renders the turns triple when loop present', () => {
    const leg: EvalQuestionLeg = {
      mark: '',
      elapsed_ms: 0,
      answer_preview: '',
      answer: '',
      run_id: null,
      recalled: [{ memory: 'a' }, { memory: 'b' }, { memory: 'c' }, { memory: 'd' }],
      retrieval_loop: loop({
        agent_turns: 3,
        turns: [
          { turn: 1, sub_queries: [sub(1), sub(2)] },
          { turn: 2, sub_queries: [sub(3)] }
        ]
      })
    };
    expect(recallCellLabel(leg)).toBe('3 turns · 4 facts');
    expect(recallLoopSaturated(leg)).toBe(false);
  });

  it('renders the turns/facts line in the expanded fold label', () => {
    const leg: EvalQuestionLeg = {
      mark: '',
      elapsed_ms: 0,
      answer_preview: '',
      answer: '',
      run_id: null,
      recalled: [{ memory: 'a' }, { memory: 'b' }],
      retrieval_loop: loop({ agent_turns: 2 })
    };
    expect(recallFoldLabel(leg)).toBe('2 turns · 2 facts');
  });

  it('flags cap saturation when agent_turns hits the cap', () => {
    const saturated = loop({ agent_turns: 4, stopped_reason: 'max_agent_turns' });
    expect(
      recallLoopSaturated({
        mark: '',
        elapsed_ms: 0,
        answer_preview: '',
        answer: '',
        run_id: null,
        retrieval_loop: saturated
      })
    ).toBe(true);
  });
});

describe('run-level histograms', () => {
  it('buckets turns per question', () => {
    const rows = [
      row({ retrieval_loop: loop({ agent_turns: 1 }) }),
      row({ retrieval_loop: loop({ agent_turns: 2 }) }),
      row({ retrieval_loop: loop({ agent_turns: 2 }) }),
      row({ retrieval_loop: loop({ agent_turns: 4, stopped_reason: 'max_agent_turns' }) })
    ];
    expect(turnsPerQuestionHistogram(rows)).toEqual({ 1: 1, 2: 2, 3: 0, 4: 1 });
  });

  it('computes decomposition rate', () => {
    const rows = [
      row({ retrieval_loop: loop({ turns: [{ turn: 1, sub_queries: [sub(1), sub(2)] }] }) }),
      row({ retrieval_loop: loop() })
    ];
    expect(decompositionRate(rows)).toBe(0.5);
    expect(decompositionRate([row({})])).toBeNull();
  });
});

describe('trajectoryPaneSnapshot', () => {
  it('singular question — one turn, one sub-query', () => {
    const snap = trajectoryPaneSnapshot(loop());
    expect(snap.turnHeaders).toEqual(['Turn 1 · 1 sub-query']);
    expect(snap.searchRows).toEqual(['S1 · goal: "goal-1"']);
    expect(snap.footer.total).toBe('2 of 4');
  });

  it('decomposed plural — multi-sub-query turn then follow-up turn', () => {
    const snap = trajectoryPaneSnapshot(
      loop({
        agent_turns: 3,
        turns: [
          { turn: 1, sub_queries: [sub(1, { goal: 'work' }), sub(2, { goal: 'pets' })] },
          { turn: 2, sub_queries: [sub(3, { goal: 'budget' })] }
        ]
      })
    );
    expect(snap.turnHeaders[0]).toContain('decomposition');
    expect(snap.searchRows).toHaveLength(3);
    expect(snap.turnHeaders[1]).toBe('Turn 2 · 1 sub-query');
  });

  it('reports the turn-cap stop reason', () => {
    const snap = trajectoryPaneSnapshot(
      loop({ agent_turns: 4, stopped_reason: 'max_agent_turns' })
    );
    expect(snap.footer.stopped).toBe('max_agent_turns');
  });
});
