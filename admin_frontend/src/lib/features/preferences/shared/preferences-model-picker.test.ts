import { describe, expect, it } from 'vitest';
import { DEFAULT_GRAPH, DEFAULT_KNOWLEDGE, type WorkspacePreferences } from '$lib/api/preferences';
import { applyModelIdToDraft } from './preferences-model-picker';

function makeDraft(): WorkspacePreferences {
  return {
    version: 1,
    llm: {
      chat_profile: null,
      vision_profile: null,
      default_stt: null,
      default_reranker: null,
      default_embedder: null,
      http_keepalive_s: 300,
      request_timeout_s: 180,
      max_retries: 2,
      default_image_gen: null,
      default_image_profile: 'image_playground'
    },
    media: {
      input: { voice: true, image: true, video: false, file: true },
      output: { voice: true, image: false, video: false, file: true }
    },
    memory: {
      enabled: true,
      user_name: '',
      search: { enabled: true },
      extraction: {
        enabled: true,
        window_turns: 4,
        chunk_min_tokens: 1000,
        session_gap_minutes: 120,
        idle_flush_hours: 12,
        instructions: ''
      },
      retrieval: {
        active_prompt_id: 'chat',
        limits: {
          max_agent_turns: 4,
          max_parallel_searches: 3,
          limit_default: 20,
          limit_min: 10,
          limit_max: 40,
          hops_max: 3
        },
        profile: null,
        render: {
          show_event_time: true,
          show_expired_at: false,
          show_superseded: false,
          max_elements_per_kind: 30,
          max_fact_chars: 240,
          max_episode_chars: 300,
          max_summary_chars: 400
        }
      }
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
    image_profiles: {},
    // Phase 7a: AI profiles + uses (edited by the Catalog's AI tabs, never by the Preferences page).
    ai: { profiles: {}, uses: {}, local_servers: {} },
    voice: { profiles: {}, uses: {}, hiro_profile: null, clip_cache_mb: 200 }
  };
}

describe('applyModelIdToDraft', () => {
  it('writes llm and graph paths', () => {
    const draft = makeDraft();
    expect(applyModelIdToDraft(draft, 'llm.default_stt', 'openai:whisper-1')).toBe(true);
    expect(draft.llm.default_stt).toBe('openai:whisper-1');
    expect(applyModelIdToDraft(draft, 'graph.reranker.model_id', 'local:bge-reranker')).toBe(true);
    expect(draft.graph.reranker.model_id).toBe('local:bge-reranker');
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
