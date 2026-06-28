import { apiRequest, type ApiResponse } from './client';
import { DEFAULT_WORKSPACE_PREFERENCES } from './generated/workspace-preferences.defaults';
import type { WorkspacePreferences } from './preferences-types';

export type {
  AnswerPromptProfile,
  ChatPreferences,
  GraphPreferences,
  ImageProfile,
  ImageProfile as ImageProfilePreference,
  KnowledgeAnsweringPreferences,
  KnowledgePreferences,
  KnowledgeRerankerPreferences,
  MemoryExtractionPreferences,
  MemorySearchPreferences,
  ModalityFlags,
  ModelTuning,
  TuningProfile,
  WorkspacePreferences
} from './preferences-types';

export const DEFAULT_MEMORY_SEARCH = DEFAULT_WORKSPACE_PREFERENCES.memory.search;
export const DEFAULT_MEMORY_EXTRACTION = DEFAULT_WORKSPACE_PREFERENCES.memory.extraction;
export const DEFAULT_KNOWLEDGE = DEFAULT_WORKSPACE_PREFERENCES.knowledge;
export const DEFAULT_GRAPH = DEFAULT_WORKSPACE_PREFERENCES.graph;
export const DEFAULT_CHAT = DEFAULT_WORKSPACE_PREFERENCES.chat;

/** Fill nested blocks when loading older preferences.json payloads or partial API data. */
export function normalizeWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  const defaults = DEFAULT_WORKSPACE_PREFERENCES;
  return {
    ...defaults,
    ...prefs,
    llm: { ...defaults.llm, ...prefs.llm },
    media: {
      input: { ...defaults.media.input, ...prefs.media?.input },
      output: { ...defaults.media.output, ...prefs.media?.output }
    },
    memory: {
      ...defaults.memory,
      ...prefs.memory,
      user_name: prefs.memory?.user_name ?? defaults.memory.user_name,
      search: { ...defaults.memory.search, ...prefs.memory?.search },
      extraction: { ...defaults.memory.extraction, ...prefs.memory?.extraction }
    },
    knowledge: {
      ...defaults.knowledge,
      ...prefs.knowledge,
      default_embedding_model_locked: prefs.knowledge?.default_embedding_model_locked,
      chunking: {
        ...defaults.knowledge.chunking,
        ...prefs.knowledge?.chunking,
        markdown: {
          ...defaults.knowledge.chunking.markdown,
          ...prefs.knowledge?.chunking?.markdown
        }
      },
      retrieval: {
        ...defaults.knowledge.retrieval,
        ...prefs.knowledge?.retrieval,
        reranker: {
          ...defaults.knowledge.retrieval.reranker,
          ...prefs.knowledge?.retrieval?.reranker
        }
      },
      answering: { ...defaults.knowledge.answering, ...prefs.knowledge?.answering },
      rewrite: { ...defaults.knowledge.rewrite, ...prefs.knowledge?.rewrite },
      default_tuning_profile:
        prefs.knowledge?.default_tuning_profile ?? defaults.knowledge.default_tuning_profile
    },
    graph: {
      ...defaults.graph,
      ...prefs.graph,
      reranker: {
        ...defaults.graph.reranker,
        ...prefs.graph?.reranker
      },
      eval: {
        ...defaults.graph.eval,
        ...prefs.graph?.eval,
        retrieval_agent: {
          ...defaults.graph.eval.retrieval_agent,
          ...prefs.graph?.eval?.retrieval_agent
        },
        retrieval_agent_prompts: {
          ...defaults.graph.eval.retrieval_agent_prompts,
          ...prefs.graph?.eval?.retrieval_agent_prompts
        }
      },
      view: {
        ...defaults.graph.view,
        ...prefs.graph?.view
      }
    },
    chat: { ...defaults.chat, ...prefs.chat },
    tuning_profiles: prefs.tuning_profiles ?? defaults.tuning_profiles,
    image_profiles: prefs.image_profiles ?? defaults.image_profiles
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
  // Dotted preference path → built-in default text for the editable system prompts. Powers the
  // "Restore default" button on prompt editors: a cleared prompt persists "" and the backend
  // pydantic default only fills ABSENT keys, so the default text is otherwise unrecoverable here.
  prompt_defaults: Record<string, string>;
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
