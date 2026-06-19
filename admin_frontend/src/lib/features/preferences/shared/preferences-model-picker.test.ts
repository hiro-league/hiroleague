import { describe, expect, it } from 'vitest';
import { DEFAULT_GRAPH, DEFAULT_KNOWLEDGE, type WorkspacePreferences } from '$lib/api/preferences';
import { applyModelIdToDraft } from './preferences-model-picker';

function makeDraft(): WorkspacePreferences {
  return {
    version: 1,
    llm: {
      default_chat: null,
      default_stt: null,
      default_tts: null,
      default_image_gen: null,
      default_tuning_profile: 'balanced_chat',
      default_image_profile: 'image_playground'
    },
    media: {
      input: { voice: true, image: true, video: false, file: true },
      output: { voice: true, image: false, video: false, file: true }
    },
    memory: {
      enabled: true,
      default_tuning_profile: 'memory_extraction',
      user_name: '',
      search: { enabled: true, top_k: 8 },
      extraction: { enabled: true }
    },
    knowledge: {
      ...DEFAULT_KNOWLEDGE,
      default_embedding_model_locked: false
    },
    graph: { ...DEFAULT_GRAPH },
    chat: {
      instructions: '',
      max_messages: 6,
      cite_sources: false,
      tools_enabled: true,
      preferred_answering_language: 'en'
    },
    tuning_profiles: {},
    image_profiles: {}
  };
}

describe('applyModelIdToDraft', () => {
  it('writes llm and graph paths', () => {
    const draft = makeDraft();
    expect(applyModelIdToDraft(draft, 'llm.default_chat', 'openai:gpt-4')).toBe(true);
    expect(draft.llm.default_chat).toBe('openai:gpt-4');
    expect(applyModelIdToDraft(draft, 'graph.extraction_model', 'anthropic:claude')).toBe(true);
    expect(draft.graph.extraction_model).toBe('anthropic:claude');
  });

  it('blocks embedding writes while locked', () => {
    const draft = makeDraft();
    draft.knowledge.default_embedding_model_locked = true;
    expect(applyModelIdToDraft(draft, 'knowledge.default_embedding_model', 'local:embed')).toBe(
      false
    );
    expect(draft.knowledge.default_embedding_model).toBeNull();
  });
});
