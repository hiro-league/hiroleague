/** Agentic retrieval-loop payload persisted on memory-eval recall legs (P5/P8, P9 shape). */

/**
 * One sub-query inside a turn's single `search_memory` call. `sid` is a globally-monotonic id
 * (the Facts-tab highlight keys on it).
 */
export type RetrievalLoopSubQuery = {
  sid: number;
  goal: string;
  query: string;
  temporal: 'current' | 'all';
  limit: number;
  hops: 1 | 2 | 3;
  show_expiry: boolean;
  returned: number;
  new: number;
  accumulated_total: number;
};

export type RetrievalLoopTurn = {
  turn: number;
  sub_queries: RetrievalLoopSubQuery[];
};

export type RetrievalLoop = {
  turns: RetrievalLoopTurn[];
  reduce: { op: string; args: Record<string, unknown> };
  /** Total LLM invocations across the loop, including the final-answer turn. */
  agent_turns: number;
  max_agent_turns: number;
  stopped_reason: 'model_answered' | 'max_agent_turns';
};
