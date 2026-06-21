import { describe, expect, it } from 'vitest';
import { DEFAULT_GRAPH } from '$lib/api/preferences';
import {
  clampRetrievalAgentLimitField,
  defaultRetrievalAgentLimits,
  RETRIEVAL_AGENT_LIMIT_BOUNDS,
  RETRIEVAL_AGENT_LIMITS_VALIDATION_MESSAGE,
  validateRetrievalAgentLimits,
  type RetrievalAgentLimits
} from './retrieval-agent-limits';

function limits(overrides: Partial<RetrievalAgentLimits> = {}): RetrievalAgentLimits {
  return { ...DEFAULT_GRAPH.eval.retrieval_agent, ...overrides };
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

describe('defaultRetrievalAgentLimits', () => {
  it('returns all six default cap values', () => {
    expect(defaultRetrievalAgentLimits()).toEqual(DEFAULT_GRAPH.eval.retrieval_agent);
  });

  it('restore_default_reverts_all_six', () => {
    const mutated = limits({
      max_agent_turns: 8,
      max_parallel_searches: 5,
      limit_default: 25,
      limit_min: 15,
      limit_max: 50,
      hops_max: 2
    });
    expect(mutated.max_agent_turns).toBe(8);
    const restored = defaultRetrievalAgentLimits();
    expect(restored).toEqual(DEFAULT_GRAPH.eval.retrieval_agent);
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

describe('GraphRetrievalAgentCard defaults', () => {
  it('renders_with_defaults', () => {
    const defaults = defaultRetrievalAgentLimits();
    expect(defaults.max_agent_turns).toBe(4);
    expect(defaults.max_parallel_searches).toBe(3);
    expect(defaults.limit_default).toBe(20);
    expect(defaults.limit_min).toBe(10);
    expect(defaults.limit_max).toBe(40);
    expect(defaults.hops_max).toBe(3);
  });
});
