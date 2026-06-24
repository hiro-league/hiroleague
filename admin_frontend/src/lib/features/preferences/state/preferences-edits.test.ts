import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CHAT,
  DEFAULT_GRAPH,
  DEFAULT_KNOWLEDGE,
  DEFAULT_MEMORY_EXTRACTION,
  DEFAULT_MEMORY_SEARCH,
  normalizeWorkspacePreferences,
  type WorkspacePreferences
} from '$lib/api/preferences';
import {
  cloneWorkspacePreferences,
  editsForSave,
  preferencesAreDirty
} from './preferences-edits';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';

const FIELD_SCHEMA = PREFERENCES_FIELD_SCHEMA;

function diffEdits(baseline: WorkspacePreferences, draft: WorkspacePreferences) {
  return editsForSave(baseline, draft, FIELD_SCHEMA);
}

function isDirty(baseline: WorkspacePreferences, draft: WorkspacePreferences) {
  return preferencesAreDirty(baseline, draft, FIELD_SCHEMA);
}

function makePrefs(overrides?: Partial<WorkspacePreferences>): WorkspacePreferences {
  const base: WorkspacePreferences = {
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
      search: { ...DEFAULT_MEMORY_SEARCH },
      extraction: { ...DEFAULT_MEMORY_EXTRACTION }
    },
    knowledge: { ...DEFAULT_KNOWLEDGE },
    graph: { ...DEFAULT_GRAPH },
    chat: { ...DEFAULT_CHAT },
    tuning_profiles: {
      balanced_chat: {
        label: 'Balanced chat',
        locked: true,
        temperature: 0.7,
        max_tokens: 2048,
        thinking: null,
        num_ctx: null
      }
    },
    image_profiles: {}
  };
  return normalizeWorkspacePreferences({ ...base, ...overrides });
}

describe('editsForSave', () => {
  it('returns no edits when baseline and draft match', () => {
    const prefs = makePrefs();
    expect(diffEdits(prefs, cloneWorkspacePreferences(prefs))).toEqual({});
    expect(isDirty(prefs, cloneWorkspacePreferences(prefs))).toBe(false);
  });

  it('emits a leaf path for a scalar change', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.memory.user_name = 'Misho';
    expect(diffEdits(baseline, draft)).toEqual({ 'memory.user_name': 'Misho' });
  });

  it('coerces cleared model ids to null', () => {
    const baseline = makePrefs();
    baseline.llm.default_chat = 'openai:gpt-4';
    const draft = cloneWorkspacePreferences(baseline);
    draft.llm.default_chat = '';
    expect(diffEdits(baseline, draft)).toEqual({ 'llm.default_chat': null });
  });

  it('coerces cleared reranker device to null', () => {
    const baseline = makePrefs();
    baseline.graph.reranker.device = 'cpu';
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.reranker.device = '';
    expect(diffEdits(baseline, draft)).toEqual({ 'graph.reranker.device': null });
  });

  it('sends tuning_profiles as one whole-object path', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.tuning_profiles.custom_1 = {
      label: 'Custom 1',
      locked: false,
      temperature: 0.5,
      max_tokens: 1024,
      thinking: null,
      num_ctx: null
    };
    const payload = diffEdits(baseline, draft);
    expect(Object.keys(payload)).toEqual(['tuning_profiles']);
    expect(payload.tuning_profiles).toEqual(draft.tuning_profiles);
  });

  it('sends graph.eval.answer_prompts as one whole-object path', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.eval.answer_prompts.custom = {
      label: 'Custom',
      locked: false,
      prompt: 'Answer from context only.'
    };
    const payload = diffEdits(baseline, draft);
    expect(Object.keys(payload)).toEqual(['graph.eval.answer_prompts']);
    expect(payload['graph.eval.answer_prompts']).toEqual(draft.graph.eval.answer_prompts);
  });

  it('sends graph.eval.retrieval_agent_prompts as one whole-object path', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.eval.retrieval_agent_prompts.custom = {
      label: 'Custom',
      locked: false,
      prompt: 'Search in parallel when plural.'
    };
    const payload = diffEdits(baseline, draft);
    expect(Object.keys(payload)).toEqual(['graph.eval.retrieval_agent_prompts']);
    expect(payload['graph.eval.retrieval_agent_prompts']).toEqual(
      draft.graph.eval.retrieval_agent_prompts
    );
  });

  it('picks up retrieval_agent scalar edits', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.eval.retrieval_agent.max_agent_turns = 6;
    draft.graph.eval.active_retrieval_agent_prompt_id = 'default';
    expect(diffEdits(baseline, draft)).toEqual({
      'graph.eval.retrieval_agent.max_agent_turns': 6
    });
  });

  it('picks_up_new_caps_paths_in_diff', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.eval.retrieval_agent = {
      max_agent_turns: 6,
      max_parallel_searches: 4,
      limit_default: 25,
      limit_min: 12,
      limit_max: 45,
      hops_max: 2
    };
    expect(diffEdits(baseline, draft)).toEqual({
      'graph.eval.retrieval_agent.max_agent_turns': 6,
      'graph.eval.retrieval_agent.max_parallel_searches': 4,
      'graph.eval.retrieval_agent.limit_default': 25,
      'graph.eval.retrieval_agent.limit_min': 12,
      'graph.eval.retrieval_agent.limit_max': 45,
      'graph.eval.retrieval_agent.hops_max': 2
    });
  });

  it('ignores read-only resolved fields', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.knowledge.answering.model_resolved = 'openai:gpt-4';
    draft.knowledge.default_embedding_model_resolved = 'some-embedder';
    expect(diffEdits(baseline, draft)).toEqual({});
  });

  it('ignores the backend-computed graph.embedder_model_resolved mirror', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    // Not in the frontend type, but the backend mirrors this @property into the payload.
    (draft.graph as unknown as Record<string, unknown>).embedder_model_resolved = 'openai:text-embed';
    expect(diffEdits(baseline, draft)).toEqual({});
  });

  it('ignores image profile and llm image defaults not edited in preferences UI', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.llm.default_image_gen = 'cloudflare:flux';
    draft.image_profiles = {
      image_playground: {
        label: 'Playground',
        locked: true,
        model: null,
        steps: 4,
        size: '1024x1024',
        style_prefix: '',
        style_suffix: '',
        seed: null
      }
    };
    expect(diffEdits(baseline, draft)).toEqual({});
  });

  it('picks up nested graph and knowledge changes without manual enumeration', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.graph.k_hop = 2;
    draft.knowledge.retrieval.top_k = 12;
    draft.chat.tools_enabled = false;
    expect(diffEdits(baseline, draft)).toEqual({
      'graph.k_hop': 2,
      'knowledge.retrieval.top_k': 12,
      'chat.tools_enabled': false
    });
  });

  it('emits media modality paths', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    draft.media.input.video = true;
    draft.media.output.image = true;
    expect(diffEdits(baseline, draft)).toEqual({
      'media.input.video': true,
      'media.output.image': true
    });
  });

  it('never emits undefined for sparse draft keys', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    delete (draft.memory as unknown as Record<string, unknown>).user_name;
    const payload = diffEdits(baseline, draft);
    expect(Object.keys(payload)).toEqual([]);
    expect(isDirty(baseline, draft)).toBe(false);
    for (const value of Object.values(payload)) {
      expect(value).not.toBe(undefined);
    }
  });

  it('coerces a removed nullable model key to null', () => {
    const baseline = makePrefs();
    baseline.llm.default_chat = 'openai:gpt-4';
    const draft = cloneWorkspacePreferences(baseline);
    delete (draft.llm as unknown as Record<string, unknown>).default_chat;
    expect(diffEdits(baseline, draft)).toEqual({ 'llm.default_chat': null });
    expect(isDirty(baseline, draft)).toBe(true);
  });

  it('throws for an unknown draft path', () => {
    const baseline = makePrefs();
    const draft = cloneWorkspacePreferences(baseline);
    (draft.graph as unknown as Record<string, unknown>).unknown_field = 'nope';
    expect(() => diffEdits(baseline, draft)).toThrow(/Unknown preference path "graph\.unknown_field"/);
  });
});
