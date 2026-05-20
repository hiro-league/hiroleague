import { apiRequest, type ApiResponse } from './client';

export type ModalityFlags = {
  voice: boolean;
  image: boolean;
  video: boolean;
  file: boolean;
};

export type ModelTuning = {
  temperature: number;
  max_tokens: number;
  thinking?: 'off' | 'minimal' | 'low' | 'medium' | 'high' | null;
};

export type TuningProfile = ModelTuning & {
  label: string;
  locked: boolean;
};

export type MemorySearchPreferences = {
  top_k: number;
  threshold: number;
  rerank: boolean;
};

export type MemoryRerankerPreferences = {
  enabled: boolean;
  model: string;
  device: string | null;
  batch_size: number;
};

export type WorkspacePreferences = {
  version: number;
  llm: {
    default_chat: string | null;
    default_stt: string | null;
    default_tts: string | null;
    default_tuning_profile: string;
  };
  media: {
    input: ModalityFlags;
    output: ModalityFlags;
  };
  memory: {
    enabled: boolean;
    default_llm: string | null;
    default_embedding_model: string | null;
    default_tuning_profile: string;
    max_messages: number;
    search: MemorySearchPreferences;
    reranker: MemoryRerankerPreferences;
  };
  tuning_profiles: Record<string, TuningProfile>;
};

export const DEFAULT_MEMORY_SEARCH: MemorySearchPreferences = {
  top_k: 8,
  threshold: 0.1,
  rerank: false
};

export const DEFAULT_MEMORY_RERANKER: MemoryRerankerPreferences = {
  enabled: false,
  model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  device: null,
  batch_size: 32
};

/** Fill nested memory blocks when loading older preferences.json payloads. */
export function normalizeWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return {
    ...prefs,
    memory: {
      ...prefs.memory,
      search: { ...DEFAULT_MEMORY_SEARCH, ...(prefs.memory.search ?? {}) },
      reranker: { ...DEFAULT_MEMORY_RERANKER, ...(prefs.memory.reranker ?? {}) }
    }
  };
}

export type PreferenceSection = {
  key: string;
  label: string;
  description: string;
};

export type PreferencesPayload = {
  preferences: WorkspacePreferences;
  sections: PreferenceSection[];
};

export type PreferencesPatchPayload = PreferencesPayload & {
  changed: string[];
};

export async function getPreferences(): Promise<ApiResponse<PreferencesPayload>> {
  return apiRequest<PreferencesPayload>('/preferences');
}

export async function patchPreferences(
  edits: Record<string, unknown>
): Promise<ApiResponse<PreferencesPatchPayload>> {
  return apiRequest<PreferencesPatchPayload>('/preferences', {
    method: 'PATCH',
    body: { edits }
  });
}
