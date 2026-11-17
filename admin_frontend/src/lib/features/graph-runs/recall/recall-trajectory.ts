/**
 * Pure derivation for the retrieval-agent trajectory tab: the footer stats, and a text snapshot of
 * the pane for tests (no DOM renderer in this project).
 */
import type { RetrievalLoop } from '$lib/api/graph-runs';

export type TrajectoryStats = {
  totalLabel: string;
  accumulatedLabel: string;
};

const DEFAULT_MAX_AGENT_TURNS = 4;

export function trajectoryStats(loop: RetrievalLoop, recalledCount: number): TrajectoryStats {
  const max = loop.max_agent_turns || DEFAULT_MAX_AGENT_TURNS;
  const peakAccumulated = loop.turns.reduce((peak, turn) => {
    for (const sub of turn.sub_queries) {
      if (sub.accumulated_total > peak) peak = sub.accumulated_total;
    }
    return peak;
  }, 0);
  return {
    totalLabel: `${loop.agent_turns} of ${max}`,
    accumulatedLabel: `${Math.max(recalledCount, peakAccumulated)} items`
  };
}

/** Text snapshot of the trajectory pane (turn headers, search rows, footer) for tests. */
export function trajectoryPaneSnapshot(loop: RetrievalLoop): {
  turnHeaders: string[];
  searchRows: string[];
  footer: Record<string, string>;
} {
  const stats = trajectoryStats(loop, 0);
  const turnHeaders = loop.turns.map((turn) => {
    const n = turn.sub_queries.length;
    const parts = [`Turn ${turn.turn}`, `${n} ${n === 1 ? 'sub-query' : 'sub-queries'}`];
    if (n > 1) parts.push('decomposition');
    return parts.join(' · ');
  });
  const searchRows = loop.turns.flatMap((turn) =>
    turn.sub_queries.map((sub) => `S${sub.sid} · goal: "${sub.goal}"`)
  );
  return {
    turnHeaders,
    searchRows,
    footer: {
      stopped: loop.stopped_reason,
      total: stats.totalLabel,
      accumulated: stats.accumulatedLabel
    }
  };
}
