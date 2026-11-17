import { describe, expect, it } from 'vitest';
import type { RetrievalLoop } from '$lib/api/graph-runs';
import { trajectoryPaneSnapshot, trajectoryStats } from './recall-trajectory';

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

describe('trajectoryStats', () => {
  it('builds footer stats', () => {
    const stats = trajectoryStats(loop(), 3);
    expect(stats.totalLabel).toBe('2 of 4');
    expect(stats.accumulatedLabel).toBe('3 items');
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
