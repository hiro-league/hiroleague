/**
 * One chat memory recall as the detail dialog shows it: the question, the retrieval agent's draft
 * answer, what it recalled, its loop, the render caps it used, and its ledger time and cost. Built
 * from a `memory_recall` ledger row plus the recall's sidecars (`/graph-runs/{run_id}/retrieval-loop`).
 */
import type {
  GraphLedgerRow,
  GraphRunRetrievalLoopResponse,
  RecallRender,
  RecalledFact,
  RetrievalLoop
} from '$lib/api/graph-runs';

export type ChatRecall = {
  runId: string;
  question: string;
  answer: string;
  recalled: RecalledFact[];
  loop: RetrievalLoop | null;
  render: RecallRender | null;
  elapsedMs: number;
  costUsd: number;
};

/** The dialog's recall from the node row and its sidecars (the row's input preview is the question). */
export function chatRecallFromLoop(
  runId: string,
  data: GraphRunRetrievalLoopResponse,
  row: GraphLedgerRow
): ChatRecall {
  const question = String(row.input_preview ?? '')
    .replace(/^q:\s*/i, '')
    .trim();
  return {
    runId,
    question: question || '(chat memory recall)',
    answer: data.answer ?? '',
    recalled: data.recalled ?? [],
    loop: data.loop ?? null,
    render: data.render ?? null,
    elapsedMs: Number(row.elapsed_ms) || 0,
    costUsd: Number(row.cost_usd) || 0
  };
}

/** True when the sidecars hold anything to show (tracing was on for the run). */
export function hasRecallDetail(data: GraphRunRetrievalLoopResponse): boolean {
  return Boolean(data.loop || (data.recalled?.length ?? 0) > 0 || data.answer);
}
