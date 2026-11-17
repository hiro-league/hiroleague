import type { CatalogModelRow } from '$lib/api/catalog';
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PreferencePath } from '$lib/api/generated/preferences-paths.generated';
import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
import { setPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';

export type PrefModelKind = 'chat' | 'stt' | 'tts' | 'embedding' | 'rerank';

// Phase 7b step 5: the chat-model fields of Hiro's jobs (default chat, knowledge answering, graph
// extraction / small, memory retrieval) and the default TTS model
// became AI- / voice-profile fields (`aiProfile` / `voiceProfile` manifest kinds), so they're gone here.
// The embedders and rerankers are profiles too (Catalog → Profiles: `embedding_profile_ref` /
// `rerank_profile_ref` fields), so speech-to-text is the one bare model field left.
export type PrefModelIdPath = 'llm.default_stt';

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

/**
 * Apply a catalog model id to the draft at `path` (always written; returns true). The write itself is
 * the generic dotted-path setter (`setPreferenceByPath`) — `PrefModelIdPath` keeps the caller
 * type-safe, so a new model field is picked up without editing this function.
 */
export function applyModelIdToDraft(
  draft: WorkspacePreferences,
  path: PrefModelIdPath,
  id: string | null
): boolean {
  setPreferenceByPath(draft, path, id);
  return true;
}
