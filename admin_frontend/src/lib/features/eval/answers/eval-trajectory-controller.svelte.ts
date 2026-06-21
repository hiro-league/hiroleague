/**
 * Pure derivation for the agentic retrieval trajectory UI (P8, P9 shape): per-row footer stats,
 * recall-column labels, and run-level histograms over ``retrieval_loop`` payloads.
 */
import type { EvalQuestionLeg } from '$lib/features/eval/shared/eval-events';
import type { EvalRow } from '$lib/features/eval/shared/eval-row';
import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';

export type TrajectoryStats = {
  reduceLabel: string;
  totalLabel: string;
  accumulatedLabel: string;
};

export type TurnsHistogram = Record<1 | 2 | 3 | 4, number>;

const DEFAULT_MAX_AGENT_TURNS = 4;

export function formatReduceLabel(reduce: RetrievalLoop['reduce']): string {
  const op = (reduce.op || 'none').trim();
  if (!op || op === 'none') return 'none';
  const args = reduce.args ?? {};
  const entries = Object.entries(args).filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (entries.length === 0) return op;
  const rendered = entries.map(([k, v]) => `${k}=${String(v)}`).join(', ');
  return `${op}(${rendered})`;
}

export function trajectoryStats(loop: RetrievalLoop, recalledCount: number): TrajectoryStats {
  const max = loop.max_agent_turns || DEFAULT_MAX_AGENT_TURNS;
  const peakAccumulated = loop.turns.reduce((peak, turn) => {
    for (const sub of turn.sub_queries) {
      if (sub.accumulated_total > peak) peak = sub.accumulated_total;
    }
    return peak;
  }, 0);
  return {
    reduceLabel: formatReduceLabel(loop.reduce),
    totalLabel: `${loop.agent_turns} of ${max}`,
    accumulatedLabel: `${Math.max(recalledCount, peakAccumulated)} items`
  };
}

export function recallCellLabel(leg: EvalQuestionLeg): string {
  const recalled = leg.recalled ?? [];
  const loop = leg.retrieval_loop;
  if (!loop) return `${recalled.length}`;
  return `${loop.agent_turns} turns · ${recalled.length} facts · ${formatReduceLabel(loop.reduce)}`;
}

export function recallLoopSaturated(leg: EvalQuestionLeg): boolean {
  const loop = leg.retrieval_loop;
  if (!loop) return false;
  const max = loop.max_agent_turns || DEFAULT_MAX_AGENT_TURNS;
  return loop.agent_turns >= max;
}

export function turnsPerQuestionHistogram(rows: EvalRow[]): TurnsHistogram {
  const buckets: TurnsHistogram = { 1: 0, 2: 0, 3: 0, 4: 0 };
  for (const row of rows) {
    const loop = row.legs.recall?.retrieval_loop;
    if (!loop) continue;
    const n = Math.min(4, Math.max(1, loop.agent_turns)) as 1 | 2 | 3 | 4;
    buckets[n] += 1;
  }
  return buckets;
}

export function decompositionRate(rows: EvalRow[]): number | null {
  const withLoop = rows.filter((row) => row.legs.recall?.retrieval_loop);
  if (withLoop.length === 0) return null;
  const decomposed = withLoop.filter((row) =>
    (row.legs.recall?.retrieval_loop?.turns ?? []).some((turn) => turn.sub_queries.length >= 2)
  ).length;
  return decomposed / withLoop.length;
}

/** Text snapshots for component tests (no DOM renderer in this project). */
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
      reduce: stats.reduceLabel,
      stopped: loop.stopped_reason,
      total: stats.totalLabel,
      accumulated: stats.accumulatedLabel
    }
  };
}
