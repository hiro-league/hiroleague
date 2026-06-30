/**
 * Model catalog for the preferences page — split out of the controller (Tier-2.2). Owns the picker
 * option lists (chat / stt / tts / embedding / rerank), the provider list, the active-providers
 * store, and catalog reload. The controller composes this and re-exposes it.
 *
 * The embedding/rerank picker options merge cloud catalog models with local-source models; the live
 * DOWNLOAD status is owned separately by `createLocalModelDownloads`.
 */
import {
  listCatalogModels,
  listCatalogProviders,
  listLocalCatalogModels,
  type CatalogModelRow,
  type CatalogProviderRow
} from '$lib/api/catalog';
import { createActiveProvidersStore } from '$lib/catalog/active-providers/active-providers-store.svelte';
import {
  catalogReloadSuccessMessage,
  reloadCatalogAndRefetch
} from '$lib/catalog/catalog-reload';
import { includeUnknownModel } from '$lib/catalog/include-unknown-model';
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export function createModelCatalog(notify: Notify) {
  const activeProvidersStore = createActiveProvidersStore();

  let chatOptions = $state<CatalogModelRow[]>([]);
  let sttOptions = $state<CatalogModelRow[]>([]);
  let ttsOptions = $state<CatalogModelRow[]>([]);
  let embeddingCatalogOptions = $state<CatalogModelRow[]>([]);
  let embeddingLocalOptions = $state<CatalogModelRow[]>([]);
  let rerankCatalogOptions = $state<CatalogModelRow[]>([]);
  let rerankLocalOptions = $state<CatalogModelRow[]>([]);
  let catalogAllProviders = $state<CatalogProviderRow[]>([]);
  let reloadBusy = $state(false);

  const embeddingPickerOptions = $derived<CatalogModelRow[]>([
    ...embeddingCatalogOptions,
    ...embeddingLocalOptions
  ]);
  const rerankPickerOptions = $derived<CatalogModelRow[]>([
    ...rerankCatalogOptions,
    ...rerankLocalOptions
  ]);

  /** Initial load: fetch every catalog kind + providers concurrently, then merge the prefs-selected
   * model ids (so an unknown/uninstalled default still shows in its picker). */
  async function load(prefs: WorkspacePreferences) {
    const [
      chatPayload,
      sttPayload,
      ttsPayload,
      embeddingPayload,
      rerankPayload,
      providersPayload,
      embeddingLocal,
      rerankLocal
    ] = await Promise.all([
      listCatalogModels({ model_kind: 'chat' }),
      listCatalogModels({ model_kind: 'stt' }),
      listCatalogModels({ model_kind: 'tts' }),
      listCatalogModels({ model_kind: 'embedding' }),
      listCatalogModels({ model_kind: 'rerank' }),
      listCatalogProviders(),
      listLocalCatalogModels('embedding'),
      listLocalCatalogModels('rerank')
    ]);
    chatOptions = prefs.llm.default_chat
      ? includeUnknownModel(chatPayload.data.models, prefs.llm.default_chat, 'chat')
      : chatPayload.data.models;
    sttOptions = prefs.llm.default_stt
      ? includeUnknownModel(sttPayload.data.models, prefs.llm.default_stt, 'stt')
      : sttPayload.data.models;
    ttsOptions = prefs.llm.default_tts
      ? includeUnknownModel(ttsPayload.data.models, prefs.llm.default_tts, 'tts')
      : ttsPayload.data.models;
    embeddingCatalogOptions = embeddingPayload.data.models;
    embeddingLocalOptions = embeddingLocal;
    rerankCatalogOptions = rerankPayload.data.models;
    rerankLocalOptions = rerankLocal;
    catalogAllProviders = providersPayload.data;
    await activeProvidersStore.load({ silent: true });
  }

  /** Rebuild the catalog from disk (clears caches), then refetch every list. */
  async function reload() {
    reloadBusy = true;
    try {
      const result = await reloadCatalogAndRefetch();
      chatOptions = result.modelsByKind.chat ?? [];
      sttOptions = result.modelsByKind.stt ?? [];
      ttsOptions = result.modelsByKind.tts ?? [];
      embeddingCatalogOptions = result.modelsByKind.embedding ?? [];
      embeddingLocalOptions = await listLocalCatalogModels('embedding');
      rerankCatalogOptions = result.modelsByKind.rerank ?? [];
      rerankLocalOptions = await listLocalCatalogModels('rerank');
      catalogAllProviders = result.providers;
      await activeProvidersStore.load({ silent: true });
      notify('success', catalogReloadSuccessMessage(result.reload));
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      reloadBusy = false;
    }
  }

  return {
    get chatOptions() {
      return chatOptions;
    },
    get sttOptions() {
      return sttOptions;
    },
    get ttsOptions() {
      return ttsOptions;
    },
    /** Embedding picker options — merged catalog + local, like rerankers. */
    get embeddingOptions() {
      return embeddingPickerOptions;
    },
    get rerankCatalogOptions() {
      return rerankCatalogOptions;
    },
    get rerankPickerOptions() {
      return rerankPickerOptions;
    },
    get catalogAllProviders() {
      return catalogAllProviders;
    },
    get activeProvidersStore() {
      return activeProvidersStore;
    },
    get reloadBusy() {
      return reloadBusy;
    },
    load,
    reload
  };
}
