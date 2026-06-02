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
import {
  getPreferences,
  normalizeWorkspacePreferences,
  patchPreferences,
  type PreferenceSection,
  type TuningProfile,
  type WorkspacePreferences
} from '$lib/api/preferences';
import {
  cancelKnowledgeReranker,
  downloadKnowledgeReranker,
  listKnowledgeRerankers,
  type LocalRerankerRow
} from '$lib/api/knowledge';
import type { ThinkingValue } from '$lib/features/preferences/shared/preferences-constants';
import {
  cloneWorkspacePreferences,
  editsForSave
} from '$lib/features/preferences/state/preferences-edits';
import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export function createPreferencesController(notify: Notify) {
  const activeProvidersStore = createActiveProvidersStore();

  let loading = $state(true);
  let busy = $state(false);
  let catalogReloadBusy = $state(false);
  let error = $state<string | null>(null);
  let sections = $state<PreferenceSection[]>([]);
  let baseline = $state<WorkspacePreferences | null>(null);
  let draft = $state<WorkspacePreferences | null>(null);
  let forceClean = $state(false);

  let chatOptions = $state<CatalogModelRow[]>([]);
  let sttOptions = $state<CatalogModelRow[]>([]);
  let ttsOptions = $state<CatalogModelRow[]>([]);
  let memoryLlmOptions = $state<CatalogModelRow[]>([]);
  let embeddingOptions = $state<CatalogModelRow[]>([]);
  // Knowledge reranker: cloud models come from the catalog; local in-process models from the
  // local-models source (provider "local"). rerankPickerOptions merges both for SingleModelPicker;
  // localRerankers carries the live download status used by the inline download affordance.
  let rerankCatalogOptions = $state<CatalogModelRow[]>([]);
  let rerankLocalOptions = $state<CatalogModelRow[]>([]);
  let localRerankers = $state<LocalRerankerRow[]>([]);
  let rerankerDownloading = $state<string | null>(null);

  const rerankPickerOptions = $derived<CatalogModelRow[]>([
    ...rerankCatalogOptions,
    ...rerankLocalOptions
  ]);
  // True while any local reranker download is in flight (click-initiated this session OR
  // resumed from the server on load) — gates starting a second download.
  const rerankerBusy = $derived(
    rerankerDownloading !== null || localRerankers.some((m) => m.status === 'downloading')
  );
  let catalogAllProviders = $state<CatalogProviderRow[]>([]);

  const dirty = $derived.by(() => {
    if (forceClean || !baseline || !draft) return false;
    return JSON.stringify(baseline) !== JSON.stringify(draft);
  });

  const canSave = $derived(dirty && !busy && !loading);

  const profileEntries = $derived.by(() =>
    Object.entries(draft?.tuning_profiles ?? {}).sort(([, a], [, b]) =>
      a.label.localeCompare(b.label)
    )
  );

  const memoryRerankerEnabled = $derived(Boolean(draft?.memory.reranker.enabled));

  const unsaved = createUnsavedGuard(
    () => dirty,
    () => true,
    (next) => {
      forceClean = !next;
    }
  );

  function setDraftFromServer(prefs: WorkspacePreferences) {
    const normalized = normalizeWorkspacePreferences(prefs);
    baseline = cloneWorkspacePreferences(normalized);
    draft = cloneWorkspacePreferences(normalized);
    forceClean = false;
  }

  function sectionLabel(key: string, fallback: string): string {
    return (sections ?? []).find((section) => section.key === key)?.label ?? fallback;
  }

  function sectionDescription(key: string): string {
    return (sections ?? []).find((section) => section.key === key)?.description ?? '';
  }

  function markDirty() {
    forceClean = false;
  }

  function rerankerDeviceValue(device: string | null | undefined): string {
    if (!device) return 'auto';
    return device;
  }

  function setRerankerDevice(value: string) {
    if (!draft) return;
    draft.memory.reranker.device = value === 'auto' ? null : value;
    markDirty();
  }

  function setRerankerEnabled(enabled: boolean) {
    if (!draft) return;
    draft.memory.reranker.enabled = enabled;
    if (!enabled) draft.memory.search.rerank = false;
    markDirty();
  }

  function setRerankerModel(modelId: string) {
    if (!draft) return;
    draft.memory.reranker.model = modelId;
    markDirty();
  }

  function setDefaultModel(path: 'default_chat' | 'default_stt' | 'default_tts', id: string | null) {
    if (!draft) return;
    draft.llm[path] = id;
    markDirty();
  }

  function setMemoryModel(path: 'default_llm' | 'default_embedding_model', id: string | null) {
    if (!draft) return;
    draft.memory[path] = id;
    draft.memory.enabled = Boolean(draft.memory.default_llm && draft.memory.default_embedding_model);
    markDirty();
  }

  function setKnowledgeEmbeddingModel(id: string | null) {
    if (!draft || draft.knowledge.default_embedding_model_locked) return;
    draft.knowledge.default_embedding_model = id;
    markDirty();
  }

  function setKnowledgeAnswerModel(id: string | null) {
    if (!draft) return;
    draft.knowledge.answering.model = id;
    markDirty();
  }

  function setKnowledgeRerankerEnabled(enabled: boolean) {
    if (!draft) return;
    draft.knowledge.retrieval.reranker.enabled = enabled;
    markDirty();
  }

  function setKnowledgeRerankerModel(id: string | null) {
    if (!draft) return;
    draft.knowledge.retrieval.reranker.model_id = id;
    markDirty();
  }

  function setKnowledgeGraphExtractionModel(id: string | null) {
    if (!draft) return;
    draft.knowledge.graph.extraction_model = id;
    markDirty();
  }

  function setKnowledgeGraphSmallModel(id: string | null) {
    if (!draft) return;
    draft.knowledge.graph.small_model = id;
    markDirty();
  }

  function setKnowledgeGraphEmbedderModel(id: string | null) {
    if (!draft) return;
    draft.knowledge.graph.embedder_model = id;
    markDirty();
  }

  // Model ids currently being polled by this browser session (so resume + click never
  // double-poll the same download). The download itself runs server-side regardless.
  const polling = new Set<string>();

  async function pollReranker(modelId: string, notifyOnDone: boolean) {
    if (polling.has(modelId)) return;
    polling.add(modelId);
    try {
      // The download runs in a server-side subprocess; poll status + byte progress until it
      // resolves. Each poll refreshes the registry rows so percent/status stay live in the UI.
      for (let i = 0; i < 1200; i++) {
        const refreshed = await listKnowledgeRerankers();
        localRerankers = refreshed.data.local ?? localRerankers;
        const row = localRerankers.find((m) => m.id === modelId);
        if (!row || row.downloaded || row.status === 'ready') {
          if (notifyOnDone) notify('success', 'Reranker downloaded.');
          return;
        }
        if (row.status === 'error') {
          if (notifyOnDone) notify('error', row.error || 'Reranker download failed.');
          return;
        }
        // Anything other than 'downloading' (e.g. cancelled → 'available') ends the poll.
        if (row.status !== 'downloading') return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    } catch {
      // Transient fetch error while polling — stop quietly; the next page load resumes.
    } finally {
      polling.delete(modelId);
    }
  }

  async function downloadReranker(modelId: string) {
    if (rerankerDownloading) return;
    rerankerDownloading = modelId;
    try {
      await downloadKnowledgeReranker(modelId);
      await pollReranker(modelId, true);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Reranker download failed.');
    } finally {
      rerankerDownloading = null;
    }
  }

  // On page load (or catalog reload), resume the live progress poll for any download that is
  // still running server-side — so returning to the page shows a ticking bar without a refresh.
  function resumeRerankerPolling() {
    for (const row of localRerankers) {
      if (row.status === 'downloading') void pollReranker(row.id, false);
    }
  }

  async function cancelReranker(modelId: string) {
    try {
      await cancelKnowledgeReranker(modelId);
      const refreshed = await listKnowledgeRerankers();
      localRerankers = refreshed.data.local ?? localRerankers;
      notify('info', 'Download cancelled.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Cancel failed.');
    }
  }

  function setDefaultTuningProfile(scope: 'llm' | 'memory' | 'knowledge', id: string) {
    if (!draft || !draft.tuning_profiles[id]) return;
    if (scope === 'llm') draft.llm.default_tuning_profile = id;
    else if (scope === 'memory') draft.memory.default_tuning_profile = id;
    else draft.knowledge.default_tuning_profile = id;
    markDirty();
  }

  function updateProfile(
    id: string,
    field: 'label' | 'temperature' | 'max_tokens' | 'thinking',
    value: string
  ) {
    if (!draft || !draft.tuning_profiles[id]) return;
    const profile = draft.tuning_profiles[id];
    if (field === 'label') profile.label = value;
    if (field === 'temperature') profile.temperature = Number(value);
    if (field === 'max_tokens') profile.max_tokens = Number(value);
    if (field === 'thinking') profile.thinking = value === 'default' ? null : (value as ThinkingValue);
    markDirty();
  }

  function createProfile() {
    if (!draft) return;
    let index = Object.keys(draft.tuning_profiles).length + 1;
    let id = `custom_${index}`;
    while (draft.tuning_profiles[id]) {
      index += 1;
      id = `custom_${index}`;
    }
    draft.tuning_profiles[id] = {
      label: `Custom ${index}`,
      locked: false,
      temperature: 0.7,
      max_tokens: 2048,
      thinking: null
    };
    markDirty();
  }

  function deleteProfile(id: string) {
    if (!draft) return;
    const profile = draft.tuning_profiles[id];
    if (!profile || profile.locked) return;
    delete draft.tuning_profiles[id];
    if (draft.llm.default_tuning_profile === id) draft.llm.default_tuning_profile = 'balanced_chat';
    if (draft.memory.default_tuning_profile === id) {
      draft.memory.default_tuning_profile = 'memory_extraction';
    }
    if (draft.knowledge.default_tuning_profile === id) {
      draft.knowledge.default_tuning_profile = 'knowledge_answering';
    }
    markDirty();
  }

  function resetLockedProfile(id: string) {
    if (!draft) return;
    if (id === 'balanced_chat') {
      draft.tuning_profiles[id] = {
        label: 'Balanced chat',
        locked: true,
        temperature: 0.7,
        max_tokens: 2048,
        thinking: null
      };
    } else if (id === 'memory_extraction') {
      draft.tuning_profiles[id] = {
        label: 'Memory extraction',
        locked: true,
        temperature: 0,
        max_tokens: 8192,
        thinking: 'low'
      };
    } else if (id === 'knowledge_answering') {
      draft.tuning_profiles[id] = {
        label: 'Knowledge answering',
        locked: true,
        temperature: 0.2,
        max_tokens: 1600,
        thinking: null
      };
    }
    markDirty();
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [
        prefsPayload,
        chatPayload,
        sttPayload,
        ttsPayload,
        embeddingPayload,
        rerankPayload,
        localRerankPayload,
        providersPayload
      ] = await Promise.all([
        getPreferences(),
        listCatalogModels({ model_kind: 'chat' }),
        listCatalogModels({ model_kind: 'stt' }),
        listCatalogModels({ model_kind: 'tts' }),
        listCatalogModels({ model_kind: 'embedding' }),
        listCatalogModels({ model_kind: 'rerank' }),
        listKnowledgeRerankers(),
        listCatalogProviders()
      ]);
      sections = prefsPayload.data.sections ?? [];
      const prefs = prefsPayload.data.preferences;
      setDraftFromServer(prefs);
      rerankCatalogOptions = rerankPayload.data.models;
      rerankLocalOptions = await listLocalCatalogModels('rerank');
      localRerankers = localRerankPayload.data.local ?? [];
      chatOptions = prefs.llm.default_chat
        ? includeUnknownModel(chatPayload.data.models, prefs.llm.default_chat, 'chat')
        : chatPayload.data.models;
      sttOptions = prefs.llm.default_stt
        ? includeUnknownModel(sttPayload.data.models, prefs.llm.default_stt, 'stt')
        : sttPayload.data.models;
      ttsOptions = prefs.llm.default_tts
        ? includeUnknownModel(ttsPayload.data.models, prefs.llm.default_tts, 'tts')
        : ttsPayload.data.models;
      memoryLlmOptions = prefs.memory.default_llm
        ? includeUnknownModel(chatPayload.data.models, prefs.memory.default_llm, 'chat')
        : chatPayload.data.models;
      embeddingOptions = prefs.memory.default_embedding_model
        ? includeUnknownModel(
            embeddingPayload.data.models,
            prefs.memory.default_embedding_model,
            'embedding'
          )
        : embeddingPayload.data.models;
      catalogAllProviders = providersPayload.data;
      await activeProvidersStore.load({ silent: true });
      resumeRerankerPolling();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load preferences.';
    } finally {
      loading = false;
    }
  }

  async function reloadCatalog() {
    catalogReloadBusy = true;
    try {
      const result = await reloadCatalogAndRefetch();
      chatOptions = result.modelsByKind.chat ?? [];
      sttOptions = result.modelsByKind.stt ?? [];
      ttsOptions = result.modelsByKind.tts ?? [];
      memoryLlmOptions = result.modelsByKind.chat ?? [];
      embeddingOptions = result.modelsByKind.embedding ?? [];
      rerankCatalogOptions = result.modelsByKind.rerank ?? [];
      rerankLocalOptions = await listLocalCatalogModels('rerank');
      catalogAllProviders = result.providers;
      await activeProvidersStore.load({ silent: true });
      notify('success', catalogReloadSuccessMessage(result.reload));
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      catalogReloadBusy = false;
    }
  }

  async function savePreferences() {
    if (!draft || !baseline || !canSave) return;
    const edits = editsForSave(baseline, draft);
    if (Object.keys(edits).length === 0) return;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      sections = payload.data.sections ?? [];
      setDraftFromServer(payload.data.preferences);
      notify('success', 'Workspace preferences saved.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  async function resetDraft() {
    if (!baseline) return;
    if (!(await unsaved.confirmDiscard())) return;
    abandonDraft();
  }

  function abandonDraft() {
    if (!baseline) return;
    draft = cloneWorkspacePreferences(baseline);
    forceClean = false;
  }

  return {
    get loading() {
      return loading;
    },
    get busy() {
      return busy;
    },
    get catalogReloadBusy() {
      return catalogReloadBusy;
    },
    get error() {
      return error;
    },
    get draft() {
      return draft;
    },
    get dirty() {
      return dirty;
    },
    get canSave() {
      return canSave;
    },
    get profileEntries(): [string, TuningProfile][] {
      return profileEntries;
    },
    get memoryRerankerEnabled() {
      return memoryRerankerEnabled;
    },
    get chatOptions() {
      return chatOptions;
    },
    get sttOptions() {
      return sttOptions;
    },
    get ttsOptions() {
      return ttsOptions;
    },
    get memoryLlmOptions() {
      return memoryLlmOptions;
    },
    get embeddingOptions() {
      return embeddingOptions;
    },
    get rerankCatalogOptions() {
      return rerankCatalogOptions;
    },
    get rerankPickerOptions() {
      return rerankPickerOptions;
    },
    get localRerankers() {
      return localRerankers;
    },
    get rerankerDownloading() {
      return rerankerDownloading;
    },
    get rerankerBusy() {
      return rerankerBusy;
    },
    get catalogAllProviders() {
      return catalogAllProviders;
    },
    get activeProvidersStore() {
      return activeProvidersStore;
    },
    get unsaved() {
      return unsaved;
    },
    sectionLabel,
    sectionDescription,
    markDirty,
    rerankerDeviceValue,
    setRerankerDevice,
    setRerankerEnabled,
    setRerankerModel,
    setDefaultModel,
    setMemoryModel,
    setKnowledgeEmbeddingModel,
    setKnowledgeAnswerModel,
    setKnowledgeRerankerEnabled,
    setKnowledgeRerankerModel,
    setKnowledgeGraphExtractionModel,
    setKnowledgeGraphSmallModel,
    setKnowledgeGraphEmbedderModel,
    downloadReranker,
    cancelReranker,
    setDefaultTuningProfile,
    updateProfile,
    createProfile,
    deleteProfile,
    resetLockedProfile,
    loadAll,
    reloadCatalog,
    savePreferences,
    resetDraft,
    abandonDraft
  };
}

export type PreferencesController = ReturnType<typeof createPreferencesController>;
