import type { CatalogModelRow } from '$lib/api/catalog';
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';

export type PrefModelKind = 'chat' | 'stt' | 'tts' | 'embedding' | 'rerank';

export type PrefModelIdPath =
  | 'llm.default_chat'
  | 'llm.default_stt'
  | 'llm.default_tts'
  | 'knowledge.default_embedding_model'
  | 'knowledge.answering.model'
  | 'knowledge.retrieval.reranker.model_id'
  | 'graph.extraction_model'
  | 'graph.small_model'
  | 'graph.embedder_model'
  | 'graph.reranker.model_id'
  | 'graph.eval.answer_model'
  | 'graph.eval.judge_model'
  | 'graph.eval.retrieval_model';

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

/** Apply a catalog model id to the draft at `path`. Returns false when the write is blocked. */
export function applyModelIdToDraft(
  draft: WorkspacePreferences,
  path: PrefModelIdPath,
  id: string | null
): boolean {
  switch (path) {
    case 'llm.default_chat':
      draft.llm.default_chat = id;
      return true;
    case 'llm.default_stt':
      draft.llm.default_stt = id;
      return true;
    case 'llm.default_tts':
      draft.llm.default_tts = id;
      return true;
    case 'knowledge.default_embedding_model':
      if (draft.knowledge.default_embedding_model_locked) return false;
      draft.knowledge.default_embedding_model = id;
      return true;
    case 'knowledge.answering.model':
      draft.knowledge.answering.model = id;
      return true;
    case 'knowledge.retrieval.reranker.model_id':
      draft.knowledge.retrieval.reranker.model_id = id;
      return true;
    case 'graph.extraction_model':
      draft.graph.extraction_model = id;
      return true;
    case 'graph.small_model':
      draft.graph.small_model = id;
      return true;
    case 'graph.embedder_model':
      draft.graph.embedder_model = id;
      return true;
    case 'graph.reranker.model_id':
      draft.graph.reranker.model_id = id;
      return true;
    case 'graph.eval.answer_model':
      draft.graph.eval.answer_model = id;
      return true;
    case 'graph.eval.judge_model':
      draft.graph.eval.judge_model = id;
      return true;
    case 'graph.eval.retrieval_model':
      draft.graph.eval.retrieval_model = id;
      return true;
    default: {
      // Exhaustiveness guard: adding a PrefModelIdPath without a case here is a compile error,
      // so a new model field can't silently no-op (skip markDirty) on select.
      const _exhaustive: never = path;
      return _exhaustive;
    }
  }
}
