import { describe, expect, it } from 'vitest';
import { DEFAULT_WORKSPACE_PREFERENCES } from '$lib/api/generated/workspace-preferences.defaults';
import {
  clampRetrievalAgentLimitField,
  RETRIEVAL_AGENT_LIMIT_BOUNDS,
  RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE,
  validateRetrievalAgentLimits,
  type RetrievalAgentLimits
} from './retrieval-agent-limits';

function limits(overrides: Partial<RetrievalAgentLimits> = {}): RetrievalAgentLimits {
  return { ...DEFAULT_WORKSPACE_PREFERENCES.memory.retrieval.limits, ...overrides };
}

describe('validateRetrievalAgentLimits', () => {
  it('accepts coherent limit_min/default/max', () => {
    expect(validateRetrievalAgentLimits(limits())).toBeNull();
  });

  it('rejects limit_min above limit_default', () => {
    expect(
      validateRetrievalAgentLimits(limits({ limit_min: 30, limit_default: 20, limit_max: 40 }))
    ).toBe(RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE);
  });

  it('rejects limit_default above limit_max', () => {
    expect(
      validateRetrievalAgentLimits(limits({ limit_min: 10, limit_default: 50, limit_max: 40 }))
    ).toBe(RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE);
  });
});

describe('clampRetrievalAgentLimitField', () => {
  it('bounds_respected_at_widget_level for max_agent_turns', () => {
    expect(clampRetrievalAgentLimitField('max_agent_turns', 0)).toBe(
      RETRIEVAL_AGENT_LIMIT_BOUNDS.max_agent_turns.min
    );
    expect(clampRetrievalAgentLimitField('max_agent_turns', 99)).toBe(
      RETRIEVAL_AGENT_LIMIT_BOUNDS.max_agent_turns.max
    );
  });

  it('bounds_respected_at_widget_level for hops_max', () => {
    expect(clampRetrievalAgentLimitField('hops_max', 0)).toBe(1);
    expect(clampRetrievalAgentLimitField('hops_max', 9)).toBe(3);
  });
});
