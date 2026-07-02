import type { CatalogModelRow } from '$lib/api/catalog';
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PreferencePath } from '$lib/api/generated/preferences-paths.generated';
import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
import { setPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';

export type PrefModelKind = 'chat' | 'stt' | 'tts' | 'embedding' | 'rerank';

export type PrefModelIdPath =
  | 'llm.default_chat'
  | 'llm.default_stt'
  | 'llm.default_tts'
  | 'llm.default_reranker'
  | 'llm.default_embedder'
  | 'knowledge.default_embedding_model'
  | 'knowledge.answering.model'
  | 'knowledge.retrieval.reranker.model_id'
  | 'graph.extraction_model'
  | 'graph.small_model'
  | 'graph.embedder_model'
  | 'graph.reranker.model_id'
  | 'graph.eval.answer_model'
  | 'graph.eval.judge_model'
  | 'graph.eval.retrieval_model'
  | 'memory.retrieval.model';

// #6: every model-id path must be a real preference path. This alias fails to compile if the
// hand-written PrefModelIdPath union ever drifts from the generated PreferencePath set.
type _AssertModelPathsArePreferencePaths<T extends PreferencePath = PrefModelIdPath> = T;

export const PREF_MODEL_EMPTY_LABELS: Record<
  PrefModelKind,
  { emptyProviders: string; emptyModelsForProvider: string }
> = {
  chat: {
    emptyProviders: 'No chat providers in catalog.',
    emptyModelsForProvider: 'No chat models for this provider.'
  },
  stt: {
    emptyProviders: 'No speech-to-text providers in catalog.',
    emptyModelsForProvider: 'No speech-to-text models for this provider.'
  },
  tts: {
    emptyProviders: 'No text-to-speech providers in catalog.',
    emptyModelsForProvider: 'No text-to-speech models for this provider.'
  },
  embedding: {
    emptyProviders: 'No embedding providers in catalog.',
    emptyModelsForProvider: 'No embedding models for this provider.'
  },
  rerank: {
    emptyProviders: 'No reranker providers.',
    emptyModelsForProvider: 'No reranker models for this provider.'
  }
};

export function prefModelCatalog(
  ctrl: PreferencesController,
  kind: PrefModelKind
): { catalogModels: CatalogModelRow[]; workspaceActiveProviderIds: Set<string> } {
  switch (kind) {
    case 'chat':
      return {
        catalogModels: ctrl.chatOptions,
        workspaceActiveProviderIds: ctrl.activeProvidersStore.chatActiveProviderIds
      };
    case 'stt':
      return {
        catalogModels: ctrl.sttOptions,
        workspaceActiveProviderIds: ctrl.activeProvidersStore.sttActiveProviderIds
      };
    case 'tts':
      return {
        catalogModels: ctrl.ttsOptions,
        workspaceActiveProviderIds: ctrl.activeProvidersStore.ttsActiveProviderIds
      };
    case 'embedding':
      return {
        catalogModels: ctrl.embeddingOptions,
        workspaceActiveProviderIds: ctrl.activeProvidersStore.embeddingActiveProviderIds
      };
    case 'rerank':
      return {
        catalogModels: ctrl.rerankPickerOptions,
        workspaceActiveProviderIds: ctrl.activeProvidersStore.rerankActiveProviderIds
      };
    default: {
      const _exhaustive: never = kind;
      return _exhaustive;
    }
  }
}

// Model paths whose write is blocked while a backend lock flag is set (dimension-bound embedders
// that can't change once data is indexed). The picker is already disabled in the UI when locked;
// this is the last-line guard so a stale enabled control can't sneak a write through. Any path not
// listed here writes unconditionally.
const MODEL_PATH_LOCK_GUARDS: Partial<
  Record<PrefModelIdPath, (draft: WorkspacePreferences) => boolean>
> = {
  'knowledge.default_embedding_model': (draft) =>
    Boolean(draft.knowledge.default_embedding_model_locked)
};

/**
 * Apply a catalog model id to the draft at `path`. Returns false when a lock guard blocks the write.
 * The write itself is the generic dotted-path setter (`setPreferenceByPath`) — `PrefModelIdPath`
 * keeps the caller type-safe, so a new model field is picked up without editing this function.
 */
export function applyModelIdToDraft(
  draft: WorkspacePreferences,
  path: PrefModelIdPath,
  id: string | null
): boolean {
  if (MODEL_PATH_LOCK_GUARDS[path]?.(draft)) return false;
  setPreferenceByPath(draft, path, id);
  return true;
}
