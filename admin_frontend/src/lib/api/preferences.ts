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

// Named image-generation recipe (image analog of TuningProfile) — model + diffusion
// params + prompt scaffolding. Edited from the Image Lab page.
export type ImageProfilePreference = {
  label: string;
  locked: boolean;
  model: string | null;
  steps: number;
  size: string | null;
  style_prefix: string;
  style_suffix: string;
  seed: number | null;
};

export type MemorySearchPreferences = {
  enabled: boolean;
  top_k: number;
};

export type MemoryExtractionPreferences = {
  enabled: boolean;
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
    // Base answer-generation system prompt; blank → relaxed backend default (partial answers allowed).
    prompt: string;
    cite_sources: boolean;
    language_policy: 'match_query' | 'prefer_english' | 'prefer_arabic';
  };
  rewrite: {
    prompt: string;
    default_on: boolean;
  };
};

// Shared Graphiti graph engine — used by BOTH knowledge retrieval and agent memory
// (promoted from knowledge.graph). `backend` off = flat Qdrant only for knowledge.
export type GraphPreferences = {
  backend: 'off' | 'graphiti';
  extraction_model: string | null;
  extraction_tuning_profile: string;
  small_model: string | null;
  small_tuning_profile: string;
  embedder_model: string | null;
  temporal_default: 'current' | 'all';
  k_hop: number;
  search_recipe: 'rrf' | 'mmr' | 'cross_encoder';
  // Which graph elements participate in fact recall. Orthogonal to search_recipe (which
  // ranks WITHIN each leg). Default 'edges' = today's behavior; 'edges_and_nodes' adds
  // EntityNode.summary recall (attribute-style memories); 'edges_nodes_episodes' also adds
  // raw conversation text via BM25 — last-resort recall, noisier. mmr × episodes is rejected
  // by the backend cross-field validator.
  search_scope: 'edges' | 'edges_and_nodes' | 'edges_nodes_episodes';
  // Cosine candidate floor (Graphiti EdgeSearchConfig.sim_min_score). Low = recall.
  sim_min_score: number;
  // Hard ceiling (seconds) on any single Kuzu query (writer + snapshot reads). Bounds the
  // checkpoint-vs-reader stall that froze the admin UI. 0 = unlimited.
  query_timeout_s: number;
  // Graph observability tier (docs §12.2). off = no graphiti ledger/tracer/sinks; ledger = one
  // priced roll-up row per episode/search (cost folds — prod default); trace = + deep per-stage
  // JSONL sidecars. Replaces the former ledger_detail (compact/rich) + the trace env vars.
  observability: 'off' | 'ledger' | 'trace';
  // Cross-encoder reranker for the fact-search leg (only when search_recipe === 'cross_encoder').
  reranker: {
    model_id: string | null;
    min_relevance: number;
    device: string | null;
  };
  // Eval-only answering knobs surfaced under the Graphiti engine settings. memory_answer_prompt
  // drives the memory-eval recall leg; blank → relaxed backend default (partial answers allowed).
  eval: {
    memory_answer_prompt: string;
  };
  // Admin graph-viz DISPLAY knobs (the shared Knowledge/Memories Graph tab's per-type node
  // filter). Frontend-only — the graph engine ignores these.
  view: {
    // A node type with more than this many instances shows a "many instances" warning in its
    // filter dropdown (the dropdown still lists + searches all; this is just a perf heads-up).
    large_type_threshold: number;
  };
};

export type ChatPreferences = {
  instructions: string;
  max_messages: number;
  cite_sources: boolean;
  tools_enabled: boolean;
  preferred_answering_language: string;
};

export type WorkspacePreferences = {
  version: number;
  llm: {
    default_chat: string | null;
    default_stt: string | null;
    default_tts: string | null;
    default_image_gen: string | null;
    default_tuning_profile: string;
    default_image_profile: string;
  };
  media: {
    input: ModalityFlags;
    output: ModalityFlags;
  };
  memory: {
    enabled: boolean;
    default_tuning_profile: string;
    // A1: the user's name, used as the Graphiti speaker label so their memory facts anchor to a
    // clean named Person hub instead of a generic "User" node. Empty ⇒ falls back to "User".
    user_name: string;
    search: MemorySearchPreferences;
    extraction: MemoryExtractionPreferences;
  };
  knowledge: KnowledgePreferences;
  graph: GraphPreferences;
  chat: ChatPreferences;
  tuning_profiles: Record<string, TuningProfile>;
  image_profiles: Record<string, ImageProfilePreference>;
};

export const DEFAULT_MEMORY_SEARCH: MemorySearchPreferences = {
  enabled: true,
  top_k: 8
};

export const DEFAULT_MEMORY_EXTRACTION: MemoryExtractionPreferences = {
  enabled: true
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
    prompt: '',
    cite_sources: true,
    language_policy: 'match_query'
  },
  rewrite: {
    prompt: '',
    default_on: false
  }
};

export const DEFAULT_GRAPH: GraphPreferences = {
  backend: 'off',
  extraction_model: null,
  extraction_tuning_profile: 'graphiti_extraction',
  small_model: null,
  small_tuning_profile: 'graphiti_small',
  embedder_model: null,
  temporal_default: 'current',
  k_hop: 1,
  search_recipe: 'rrf',
  search_scope: 'edges',
  sim_min_score: 0.3,
  query_timeout_s: 60,
  observability: 'ledger',
  reranker: {
    model_id: null,
    min_relevance: 0.0,
    device: null
  },
  eval: {
    memory_answer_prompt: ''
  },
  view: {
    large_type_threshold: 200
  }
};

export const DEFAULT_CHAT: ChatPreferences = {
  instructions: '',
  max_messages: 6,
  cite_sources: false,
  tools_enabled: true,
  preferred_answering_language: 'en'
};

/** Fill nested memory blocks when loading older preferences.json payloads. */
export function normalizeWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return {
    ...prefs,
    // Older payloads predate image generation — fill the llm defaults and profile map.
    llm: {
      ...prefs.llm,
      default_image_gen: prefs.llm.default_image_gen ?? null,
      default_image_profile: prefs.llm.default_image_profile ?? 'image_playground'
    },
    image_profiles: prefs.image_profiles ?? {},
    chat: { ...DEFAULT_CHAT, ...(prefs.chat ?? {}) },
    memory: {
      ...prefs.memory,
      // Older payloads predate the A1 speaker-anchor field — default to "" (⇒ "User" fallback).
      user_name: prefs.memory.user_name ?? '',
      search: { ...DEFAULT_MEMORY_SEARCH, ...(prefs.memory.search ?? {}) },
      extraction: { ...DEFAULT_MEMORY_EXTRACTION, ...(prefs.memory.extraction ?? {}) }
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
    },
    graph: {
      ...DEFAULT_GRAPH,
      ...(prefs.graph ?? {}),
      reranker: {
        ...DEFAULT_GRAPH.reranker,
        ...(prefs.graph?.reranker ?? {})
      },
      eval: {
        ...DEFAULT_GRAPH.eval,
        ...(prefs.graph?.eval ?? {})
      },
      // Older payloads predate the graph-viz display knobs — fill from defaults.
      view: {
        ...DEFAULT_GRAPH.view,
        ...(prefs.graph?.view ?? {})
      }
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
