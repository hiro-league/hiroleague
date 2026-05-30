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
  enabled: boolean;
  top_k: number;
  threshold: number;
  rerank: boolean;
};

export type MemoryExtractionPreferences = {
  enabled: boolean;
};

export type MemoryRerankerPreferences = {
  enabled: boolean;
  model: string;
  device: string | null;
  batch_size: number;
};

export type KnowledgeRerankerPreferences = {
  enabled: boolean;
  // Catalog provider:model (cloud) OR a local-registry id (local:*). Null = no reranker.
  model_id: string | null;
  top_n: number;
  device: string | null;
  batch_size: number;
};

export type KnowledgePreferences = {
  default_embedding_model: string | null;
  default_embedding_model_resolved?: string | null;
  default_embedding_model_locked?: boolean;
  chunking: {
    chunk_size: number;
    chunk_overlap: number;
    embed_structural_context: boolean;
    markdown: {
      respect_headings: boolean;
    };
  };
  retrieval: {
    top_k: number;
    min_score: number;
    // Hybrid (dense + BM25 sparse, RRF) retrieval. min_score applies to the dense branch.
    hybrid: boolean;
    sparse_model: string;
    prefetch_limit: number;
    reranker: KnowledgeRerankerPreferences;
  };
  default_tuning_profile: string;
  answering: {
    model: string | null;
    model_resolved?: string | null;
    model_resolved_source?: string | null;
    cite_sources: boolean;
    language_policy: 'match_query' | 'prefer_english' | 'prefer_arabic';
  };
  rewrite: {
    prompt: string;
    default_on: boolean;
  };
};

export type ChatPreferences = {
  instructions: string;
  max_messages: number;
  cite_sources: boolean;
  preferred_answering_language: string;
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
    search: MemorySearchPreferences;
    extraction: MemoryExtractionPreferences;
    reranker: MemoryRerankerPreferences;
  };
  knowledge: KnowledgePreferences;
  chat: ChatPreferences;
  tuning_profiles: Record<string, TuningProfile>;
};

export const DEFAULT_MEMORY_SEARCH: MemorySearchPreferences = {
  enabled: true,
  top_k: 8,
  threshold: 0.1,
  rerank: false
};

export const DEFAULT_MEMORY_EXTRACTION: MemoryExtractionPreferences = {
  enabled: true
};

export const DEFAULT_MEMORY_RERANKER: MemoryRerankerPreferences = {
  enabled: false,
  model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  device: null,
  batch_size: 32
};

export const DEFAULT_KNOWLEDGE: KnowledgePreferences = {
  default_embedding_model: null,
  default_embedding_model_resolved: 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
  default_tuning_profile: 'knowledge_answering',
  chunking: {
    chunk_size: 1200,
    chunk_overlap: 150,
    embed_structural_context: true,
    markdown: { respect_headings: true }
  },
  retrieval: {
    top_k: 20,
    min_score: 0,
    hybrid: true,
    sparse_model: 'Qdrant/bm25',
    prefetch_limit: 40,
    reranker: {
      enabled: false,
      model_id: null,
      top_n: 8,
      device: null,
      batch_size: 32
    }
  },
  answering: {
    model: null,
    model_resolved: null,
    cite_sources: true,
    language_policy: 'match_query'
  },
  rewrite: {
    prompt: '',
    default_on: false
  }
};

export const DEFAULT_CHAT: ChatPreferences = {
  instructions: '',
  max_messages: 6,
  cite_sources: false,
  preferred_answering_language: 'en'
};

/** Fill nested memory blocks when loading older preferences.json payloads. */
export function normalizeWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return {
    ...prefs,
    chat: { ...DEFAULT_CHAT, ...(prefs.chat ?? {}) },
    memory: {
      ...prefs.memory,
      search: { ...DEFAULT_MEMORY_SEARCH, ...(prefs.memory.search ?? {}) },
      extraction: { ...DEFAULT_MEMORY_EXTRACTION, ...(prefs.memory.extraction ?? {}) },
      reranker: { ...DEFAULT_MEMORY_RERANKER, ...(prefs.memory.reranker ?? {}) }
    },
    knowledge: {
      ...DEFAULT_KNOWLEDGE,
      ...(prefs.knowledge ?? {}),
      chunking: {
        ...DEFAULT_KNOWLEDGE.chunking,
        ...(prefs.knowledge?.chunking ?? {}),
        markdown: {
          ...DEFAULT_KNOWLEDGE.chunking.markdown,
          ...(prefs.knowledge?.chunking?.markdown ?? {})
        }
      },
      retrieval: {
        ...DEFAULT_KNOWLEDGE.retrieval,
        ...(prefs.knowledge?.retrieval ?? {}),
        reranker: {
          ...DEFAULT_KNOWLEDGE.retrieval.reranker,
          ...(prefs.knowledge?.retrieval?.reranker ?? {})
        }
      },
      answering: { ...DEFAULT_KNOWLEDGE.answering, ...(prefs.knowledge?.answering ?? {}) },
      rewrite: { ...DEFAULT_KNOWLEDGE.rewrite, ...(prefs.knowledge?.rewrite ?? {}) },
      default_tuning_profile:
        prefs.knowledge?.default_tuning_profile ?? DEFAULT_KNOWLEDGE.default_tuning_profile
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
