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
      embedder_profile_locked: false
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
    ai: { profiles: {}, uses: {}, local_servers: {}, folders: {} },
    voice: { profiles: {}, uses: {}, hiro_profile: null, clip_cache_mb: 200 },
    embedding: { profiles: {}, uses: {} },
    rerank: { profiles: {}, uses: {} }
  };
}

describe('applyModelIdToDraft', () => {
  // Embedders and rerankers are profiles now (searchProfile fields): speech-to-text is the one model field.
  it('writes the speech-to-text model', () => {
    const draft = makeDraft();
    expect(applyModelIdToDraft(draft, 'llm.default_stt', 'openai:whisper-1')).toBe(true);
    expect(draft.llm.default_stt).toBe('openai:whisper-1');
  });
});
