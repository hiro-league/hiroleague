/**
 * Hand-written preference types: re-exports from codegen plus API-only computed fields.
 * Never edit `generated/*` — run `npm run gen:prefs-types` after backend model changes.
 */
import type {
  AnswerPromptProfile,
  ChatPreferences,
  GraphPreferences,
  ImageProfile,
  KnowledgePreferences as GeneratedKnowledgePreferences,
  KnowledgeAnsweringPreferences as GeneratedKnowledgeAnsweringPreferences,
  KnowledgeRerankerPreferences,
  MemoryExtractionPreferences,
  MemorySearchPreferences,
  ModalityFlags,
  TuningProfile,
  WorkspacePreferences as GeneratedWorkspacePreferences
} from './generated/preferences.generated';

export type {
  AnswerPromptProfile,
  ChatPreferences,
  GraphPreferences,
  ImageProfile,
  ImageProfile as ImageProfilePreference,
  KnowledgeRerankerPreferences,
  MemoryExtractionPreferences,
  MemorySearchPreferences,
  ModalityFlags,
  TuningProfile
} from './generated/preferences.generated';

export type ModelTuning = Pick<TuningProfile, 'temperature' | 'max_tokens' | 'thinking' | 'num_ctx'>;

export type KnowledgeAnsweringPreferences = GeneratedKnowledgeAnsweringPreferences & {
  model_resolved?: string | null;
  model_resolved_source?: string | null;
};

/** Persisted knowledge prefs plus admin GET payload enrichments. */
export type KnowledgePreferences = Omit<GeneratedKnowledgePreferences, 'answering'> & {
  default_embedding_model_resolved?: string | null;
  default_embedding_model_locked?: boolean;
  answering: KnowledgeAnsweringPreferences;
};

/** Workspace preferences as returned by GET/PATCH (persisted shape + computed fields). */
export type WorkspacePreferences = Omit<GeneratedWorkspacePreferences, 'knowledge'> & {
  knowledge: KnowledgePreferences;
};
