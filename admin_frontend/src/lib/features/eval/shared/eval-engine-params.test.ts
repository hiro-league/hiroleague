import { describe, expect, it } from 'vitest';
import type { WorkspacePreferences } from '$lib/api/preferences';
import { trackConfig } from './eval-tracks';
import {
  aiEngineLine,
  answerPromptLabelFor,
  answerPromptOptions,
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
        answer_prompts: {
          default: { label: 'Default (grounded)', locked: true, prompt: '' },
          terse: { label: 'Terse', locked: false, prompt: 'be terse' }
        }
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
  it('memory includes the Small ingest model + eval answer model', () => {
    const lines = modelLines(prefs(), MEMORY);
    expect(lines.map((l) => l.label)).toEqual(['Extraction', 'Small', 'Embedder', 'Answer', 'Judge']);
    expect(lines.find((l) => l.label === 'Answer')?.model).toBe('ans-model');
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
  it('memory shows recall top-k + answer prompt provenance', () => {
    const labels = recallKnobs(prefs(), MEMORY, 'Terse').map((p) => p.label);
    expect(labels).toContain('Recall top-k');
    expect(labels).toContain('Answer prompt');
  });
  it('knowledge shows flat retrieval knobs', () => {
    const labels = recallKnobs(prefs(), KNOWLEDGE, '').map((p) => p.label);
    expect(labels).toContain('Retrieval top-k');
    expect(labels).toContain('Hybrid');
  });
});

describe('answerPromptOptions / label', () => {
  it('lists default first (value "") then the rest', () => {
    const opts = answerPromptOptions(prefs());
    expect(opts[0]).toEqual({ id: '', label: 'Default (grounded)' });
    expect(opts.map((o) => o.id)).toEqual(['', 'terse']);
  });
  it('resolves a label by id, falling back to the first option', () => {
    const opts = answerPromptOptions(prefs());
    expect(answerPromptLabelFor(opts, 'terse')).toBe('Terse');
    expect(answerPromptLabelFor(opts, 'missing')).toBe('Default (grounded)');
  });
  it('handles null prefs', () => {
    expect(answerPromptOptions(null)).toEqual([{ id: '', label: 'Default' }]);
  });
});

describe('aiEngineLine', () => {
  it('summarizes backend/recipe/hops/answer', () => {
    expect(aiEngineLine(prefs())).toBe('kuzu · recipe=hybrid · hops=2 · answer=kb-answer-resolved');
    expect(aiEngineLine(null)).toBe('');
  });
});
