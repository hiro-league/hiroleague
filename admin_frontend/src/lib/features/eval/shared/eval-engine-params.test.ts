import { describe, expect, it } from 'vitest';
import type { WorkspacePreferences } from '$lib/api/preferences';
import { trackConfig } from './eval-tracks';
import {
  aiEngineLine,
  ingestKnobs,
  modelLines,
  recallKnobs,
  tuningChips
} from './eval-engine-params';

// Minimal prefs shape covering only the fields these derivations read. Cast through unknown so
// the test stays focused (the full WorkspacePreferences type is large + irrelevant here).
function prefs(overrides: Record<string, unknown> = {}): WorkspacePreferences {
  const base = {
    graph: {
      backend: 'kuzu',
      extraction_model: 'x-model',
      extraction_tuning_profile: 'tp_extract',
      small_model: 's-model',
      small_tuning_profile: 'tp_small',
      embedder_model: 'e-model',
      entity_ontology: 'open',
      temporal_default: 'current',
      k_hop: 2,
      search_recipe: 'hybrid',
      search_scope: 'group',
      sim_min_score: 0.3,
      observability: 'trace',
      reranker: { model_id: 'rr', min_relevance: 0.5 },
      eval: {
        answer_model: 'ans-model',
        answer_tuning_profile: 'tp_answer',
        judge_model: 'judge-model',
        judge_tuning_profile: 'tp_judge',
        // Retrieval agent (memory recall is agentic) — model unset → falls back to the answer model.
        retrieval_model: null,
        retrieval_tuning_profile: 'tp_retrieval',
        retrieval_agent: {
          max_agent_turns: 4,
          max_parallel_searches: 3,
          limit_default: 20,
          limit_min: 5,
          limit_max: 40,
          hops_max: 2
        },
        retrieval_agent_prompts: { default: { label: 'Default agent', locked: true, prompt: '' } },
        active_retrieval_agent_prompt_id: 'default',
        answer_prompts: {
          default: { label: 'Default (grounded)', locked: true, prompt: '' },
          terse: { label: 'Terse', locked: false, prompt: 'be terse' }
        },
        active_answer_prompt_id: 'terse'
      }
    },
    knowledge: {
      answering: { model: 'kb-answer', model_resolved: 'kb-answer-resolved' },
      default_tuning_profile: 'knowledge_answering',
      chunking: { chunk_size: 512, chunk_overlap: 64, embed_structural_context: true },
      retrieval: {
        top_k: 8,
        min_score: 0.2,
        hybrid: true,
        prefetch_limit: 40,
        reranker: { enabled: false, model_id: null, top_n: 5 }
      }
    },
    memory: { search: { top_k: 6 } },
    tuning_profiles: {
      tp_answer: { label: 'Answer', locked: false, temperature: 0.2, max_tokens: 1600, thinking: 'low' },
      tp_extract: { label: 'Extract', locked: false, temperature: 0, max_tokens: 800 }
    }
  };
  return { ...base, ...overrides } as unknown as WorkspacePreferences;
}

const MEMORY = trackConfig('memory');
const KNOWLEDGE = trackConfig('knowledge');

describe('tuningChips', () => {
  it('formats temp/max and optional thinking', () => {
    expect(tuningChips(prefs(), 'tp_answer')).toBe('temp 0.2 · max 1600 · think low');
    expect(tuningChips(prefs(), 'tp_extract')).toBe('temp 0 · max 800');
  });
  it('returns empty for missing / unknown profiles', () => {
    expect(tuningChips(prefs(), undefined)).toBe('');
    expect(tuningChips(prefs(), 'nope')).toBe('');
  });
});

describe('modelLines', () => {
  it('memory includes the Small ingest model + the retrieval agent before answer/judge', () => {
    const lines = modelLines(prefs(), MEMORY);
    expect(lines.map((l) => l.label)).toEqual([
      'Extraction',
      'Small',
      'Embedder',
      'Retrieval',
      'Answer',
      'Judge'
    ]);
    expect(lines.find((l) => l.label === 'Answer')?.model).toBe('ans-model');
    // Retrieval model unset → falls back to the eval answer model.
    expect(lines.find((l) => l.label === 'Retrieval')?.model).toBe('ans-model');
  });
  it('knowledge omits Small and answers with the production pipeline', () => {
    const lines = modelLines(prefs(), KNOWLEDGE);
    expect(lines.map((l) => l.label)).toEqual(['Extraction', 'Embedder', 'Answer', 'Judge']);
    expect(lines.find((l) => l.label === 'Answer')?.model).toBe('kb-answer-resolved');
  });
});

describe('ingestKnobs', () => {
  it('knowledge adds chunking knobs; memory does not', () => {
    expect(ingestKnobs(prefs(), MEMORY).map((p) => p.label)).toEqual(['Extraction ontology']);
    expect(ingestKnobs(prefs(), KNOWLEDGE).map((p) => p.label)).toContain('Chunk size');
  });
});

describe('recallKnobs', () => {
  it('memory shows the retrieval agent knobs before the active answer-prompt provenance', () => {
    const knobs = recallKnobs(prefs(), MEMORY);
    const labels = knobs.map((p) => p.label);
    expect(labels).toContain('Agent turns');
    expect(labels).toContain('Search limit');
    expect(labels).toContain('Retrieval prompt');
    expect(labels).toContain('Answer prompt');
    // Answer-prompt provenance now resolves the persisted active_answer_prompt_id (= 'terse').
    expect(knobs.find((p) => p.label === 'Answer prompt')?.value).toBe('Terse');
    // The agentic recall agent's knobs precede the answer-step knob; the dead `memory.search.top_k`
    // (Recall top-k) is gone.
    expect(labels).not.toContain('Recall top-k');
    expect(labels.indexOf('Search limit')).toBeLessThan(labels.indexOf('Answer prompt'));
  });
  it('falls back to the locked default profile label when the active id is unknown', () => {
    const p = prefs();
    p.graph.eval.active_answer_prompt_id = 'missing';
    const knobs = recallKnobs(p, MEMORY);
    expect(knobs.find((k) => k.label === 'Answer prompt')?.value).toBe('Default (grounded)');
  });
  it('knowledge shows flat retrieval knobs', () => {
    const labels = recallKnobs(prefs(), KNOWLEDGE).map((p) => p.label);
    expect(labels).toContain('Retrieval top-k');
    expect(labels).toContain('Hybrid');
  });
});

describe('aiEngineLine', () => {
  it('summarizes backend/recipe/hops/answer', () => {
    expect(aiEngineLine(prefs())).toBe('kuzu · recipe=hybrid · hops=2 · answer=kb-answer-resolved');
    expect(aiEngineLine(null)).toBe('');
  });
});
