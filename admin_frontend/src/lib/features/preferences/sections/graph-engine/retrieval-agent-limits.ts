import { DEFAULT_GRAPH, type GraphPreferences } from '$lib/api/preferences';

export type RetrievalAgentLimits = GraphPreferences['eval']['retrieval_agent'];

export const RETRIEVAL_AGENT_LIMIT_BOUNDS = {
  max_agent_turns: { min: 1, max: 10 },
  max_parallel_searches: { min: 1, max: 5 },
  limit_default: { min: 1, max: 100 },
  limit_min: { min: 1, max: 100 },
  limit_max: { min: 1, max: 100 },
  hops_max: { min: 1, max: 3 }
} as const;

export const RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE =
  'limit_min ≤ limit_default ≤ limit_max';

/** Cross-field check mirroring pydantic RetrievalAgentLimits._coherent_limits. */
export function validateRetrievalAgentLimits(limits: RetrievalAgentLimits): string | null {
  if (limits.limit_min > limits.limit_default || limits.limit_default > limits.limit_max) {
    return RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE;
  }
  return null;
}

export function defaultRetrievalAgentLimits(): RetrievalAgentLimits {
  return { ...DEFAULT_GRAPH.eval.retrieval_agent };
}

/** Clamp a single cap field to its widget bounds (mirrors pydantic ge/le). */
export function clampRetrievalAgentLimitField<K extends keyof typeof RETRIEVAL_AGENT_LIMIT_BOUNDS>(
  field: K,
  value: number
): number {
  const { min, max } = RETRIEVAL_AGENT_LIMIT_BOUNDS[field];
  return Math.min(max, Math.max(min, value));
}
