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
import { getPreferencesSchema } from '$lib/api/preferences-schema';
import {
  cancelKnowledgeEmbedder,
  cancelKnowledgeReranker,
  downloadKnowledgeEmbedder,
  downloadKnowledgeReranker,
  listKnowledgeEmbedders,
  listKnowledgeRerankers,
  type LocalEmbedderRow,
  type LocalRerankerRow
} from '$lib/api/knowledge';
import type { ThinkingValue } from '$lib/features/preferences/shared/preferences-constants';
import {
  applyModelIdToDraft,
  type PrefModelIdPath
} from '$lib/features/preferences/shared/preferences-model-picker';
import {
  cloneWorkspacePreferences,
  editsForSave,
  getPreferenceByPath,
  preferencesAreDirty,
  setPreferenceByPath
} from '$lib/features/preferences/state/preferences-edits';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import type { PreferencesSchemaMap } from '$lib/features/preferences/shared/preferences-schema';
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
  // Built-in default texts for the editable system prompts (dotted path → text), from the
  // preferences payload. Powers the "Restore default" button: a cleared prompt persists "" and
  // the backend default only fills absent keys, so the UI can't recover the text on its own.
  let promptDefaults = $state<Record<string, string>>({});
  let fieldSchema = $state<PreferencesSchemaMap | null>(null);
  let baseline = $state<WorkspacePreferences | null>(null);
  let draft = $state<WorkspacePreferences | null>(null);
  let forceClean = $state(false);
  // Per-section validation errors (e.g. cross-field caps on the Retrieval Agent card).
  let sectionErrors = $state<Record<string, string | null>>({});

  let chatOptions = $state<CatalogModelRow[]>([]);
  let sttOptions = $state<CatalogModelRow[]>([]);
  let ttsOptions = $state<CatalogModelRow[]>([]);
  // Embedding: cloud models from the catalog; local FastEmbed models from the local-models source
  // (provider "local"). embeddingPickerOptions merges both for SingleModelPicker; localEmbedders
  // carries the live download status used by the inline download affordance (same as rerankers).
  let embeddingCatalogOptions = $state<CatalogModelRow[]>([]);
  let embeddingLocalOptions = $state<CatalogModelRow[]>([]);
  let localEmbedders = $state<LocalEmbedderRow[]>([]);
  let embedderDownloading = $state<string | null>(null);
  // Knowledge reranker: cloud models come from the catalog; local in-process models from the
  // local-models source (provider "local"). rerankPickerOptions merges both for SingleModelPicker;
  // localRerankers carries the live download status used by the inline download affordance.
  let rerankCatalogOptions = $state<CatalogModelRow[]>([]);
  let rerankLocalOptions = $state<CatalogModelRow[]>([]);
  let localRerankers = $state<LocalRerankerRow[]>([]);
  let rerankerDownloading = $state<string | null>(null);

  const embeddingPickerOptions = $derived<CatalogModelRow[]>([
    ...embeddingCatalogOptions,
    ...embeddingLocalOptions
  ]);
  const embedderBusy = $derived(
    embedderDownloading !== null || localEmbedders.some((m) => m.status === 'downloading')
  );
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

  const effectiveFieldSchema = $derived<PreferencesSchemaMap>(
    fieldSchema ?? PREFERENCES_FIELD_SCHEMA
  );

  const dirty = $derived.by(() => {
    if (forceClean || !baseline || !draft) return false;
    return preferencesAreDirty(baseline, draft, effectiveFieldSchema);
  });

  const hasSectionErrors = $derived(
    Object.values(sectionErrors).some((message) => message != null && message !== '')
  );
  const canSave = $derived(dirty && !busy && !loading && !hasSectionErrors);

  const profileEntries = $derived.by(() =>
    Object.entries(draft?.tuning_profiles ?? {}).sort(([, a], [, b]) =>
      a.label.localeCompare(b.label)
    )
  );

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

  function setSectionError(sectionId: string, message: string | null) {
    if (sectionErrors[sectionId] === message) return;
    sectionErrors = { ...sectionErrors, [sectionId]: message };
  }

  function setModelId(path: PrefModelIdPath, id: string | null) {
    if (!draft) return;
    if (applyModelIdToDraft(draft, path, id)) markDirty();
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

  // Local embedder downloads — same lifecycle as rerankers (poll status + byte progress).
  async function pollEmbedder(modelId: string, notifyOnDone: boolean) {
    if (polling.has(modelId)) return;
    polling.add(modelId);
    try {
      for (let i = 0; i < 1200; i++) {
        const refreshed = await listKnowledgeEmbedders();
        localEmbedders = refreshed.data.local ?? localEmbedders;
        const row = localEmbedders.find((m) => m.id === modelId);
        if (!row || row.downloaded || row.status === 'ready') {
          if (notifyOnDone) notify('success', 'Embedder downloaded.');
          return;
        }
        if (row.status === 'error') {
          if (notifyOnDone) notify('error', row.error || 'Embedder download failed.');
          return;
        }
        if (row.status !== 'downloading') return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    } catch {
      // Transient fetch error while polling — stop quietly; the next page load resumes.
    } finally {
      polling.delete(modelId);
    }
  }

  async function downloadEmbedder(modelId: string) {
    if (embedderDownloading) return;
    embedderDownloading = modelId;
    try {
      await downloadKnowledgeEmbedder(modelId);
      await pollEmbedder(modelId, true);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Embedder download failed.');
    } finally {
      embedderDownloading = null;
    }
  }

  function resumeEmbedderPolling() {
    for (const row of localEmbedders) {
      if (row.status === 'downloading') void pollEmbedder(row.id, false);
    }
  }

  async function cancelEmbedder(modelId: string) {
    try {
      await cancelKnowledgeEmbedder(modelId);
      const refreshed = await listKnowledgeEmbedders();
      localEmbedders = refreshed.data.local ?? localEmbedders;
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
    field: 'label' | 'temperature' | 'max_tokens' | 'thinking' | 'num_ctx',
    value: string
  ) {
    if (!draft || !draft.tuning_profiles[id]) return;
    const profile = draft.tuning_profiles[id];
    if (field === 'label') profile.label = value;
    if (field === 'temperature') profile.temperature = Number(value);
    if (field === 'max_tokens') profile.max_tokens = Number(value);
    if (field === 'thinking') profile.thinking = value === 'default' ? null : (value as ThinkingValue);
    // Blank = unset (null) → provider default; otherwise the Ollama num_ctx override.
    if (field === 'num_ctx') profile.num_ctx = value.trim() === '' ? null : Number(value);
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
      thinking: null,
      num_ctx: null
    };
    markDirty();
  }

  // Duplicate any profile (built-in or custom) into a new editable custom profile. The table view
  // makes "clone the closest preset, then tweak" the happy path for creating a profile.
  function duplicateProfile(id: string) {
    if (!draft) return;
    const source = draft.tuning_profiles[id];
    if (!source) return;
    let index = Object.keys(draft.tuning_profiles).length + 1;
    let newId = `custom_${index}`;
    while (draft.tuning_profiles[newId]) {
      index += 1;
      newId = `custom_${index}`;
    }
    draft.tuning_profiles[newId] = {
      label: `${source.label.trim() || id} (copy)`,
      locked: false,
      temperature: source.temperature,
      max_tokens: source.max_tokens,
      thinking: source.thinking,
      num_ctx: source.num_ctx
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
        thinking: null,
        num_ctx: null
      };
    } else if (id === 'memory_extraction') {
      draft.tuning_profiles[id] = {
        label: 'Memory extraction',
        locked: true,
        temperature: 0,
        max_tokens: 8192,
        thinking: 'low',
        num_ctx: null
      };
    } else if (id === 'knowledge_answering') {
      draft.tuning_profiles[id] = {
        label: 'Knowledge answering',
        locked: true,
        temperature: 0.2,
        max_tokens: 1600,
        thinking: null,
        num_ctx: null
      };
    }
    markDirty();
  }

  // Persist a SINGLE tuning profile to the backend immediately (the inline profile editor's
  // "Update"), independent of the page-level Save. Editing a shared profile applies to every
  // model referencing it. We diff just this profile's subtree so only its changed leaves PATCH,
  // then commit the result into both baseline and draft — leaving any other pending draft edits
  // untouched (so this never silently saves unrelated changes, and the page stays accurately dirty).
  async function saveProfileNow(id: string, next: TuningProfile) {
    if (!draft || !baseline || !draft.tuning_profiles[id]) return;
    busy = true;
    try {
      const probe = cloneWorkspacePreferences(baseline);
      probe.tuning_profiles[id] = next;
      const edits = editsForSave(baseline, probe, effectiveFieldSchema);
      if (Object.keys(edits).length === 0) return;
      const payload = await patchPreferences(edits);
      const saved = payload.data.preferences.tuning_profiles[id] ?? next;
      baseline.tuning_profiles[id] = JSON.parse(JSON.stringify(saved)) as TuningProfile;
      draft.tuning_profiles[id] = JSON.parse(JSON.stringify(saved)) as TuningProfile;
      notify('success', 'Tuning profile saved.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  // Persist one or more prompt paths to the backend IMMEDIATELY from a prompt-editor dialog,
  // independent of the page-level Save. The prompt cards no longer bind ctrl.draft directly (the
  // dialog edits a local working copy), so these paths normally sit equal in baseline and draft;
  // here we PATCH just the given edits and commit the server-effective values back into BOTH
  // baseline and draft for exactly those paths — leaving any other pending draft edits untouched
  // (so the page stays accurately dirty and never silently saves unrelated changes). Returns true
  // on success. `edits` is a dotted-path → value map (single prompt string, or whole writeWhole
  // dict for a prompt library), matching the page-save payload shape.
  async function saveDialogEdits(edits: Record<string, unknown>): Promise<boolean> {
    if (!draft || !baseline || Object.keys(edits).length === 0) return false;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      const saved = payload.data.preferences;
      for (const path of Object.keys(edits)) {
        const value = getPreferenceByPath(saved, path);
        // Clone so baseline and draft never share a mutable reference for the committed path.
        setPreferenceByPath(baseline, path, JSON.parse(JSON.stringify(value ?? null)));
        setPreferenceByPath(draft, path, JSON.parse(JSON.stringify(value ?? null)));
      }
      promptDefaults = payload.data.prompt_defaults ?? promptDefaults;
      sections = payload.data.sections ?? sections;
      notify('success', 'Prompt saved.');
      return true;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
      return false;
    } finally {
      busy = false;
    }
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [
        prefsPayload,
        schemaPayload,
        chatPayload,
        sttPayload,
        ttsPayload,
        embeddingPayload,
        rerankPayload,
        localRerankPayload,
        localEmbedderPayload,
        providersPayload
      ] = await Promise.all([
        getPreferences(),
        getPreferencesSchema(),
        listCatalogModels({ model_kind: 'chat' }),
        listCatalogModels({ model_kind: 'stt' }),
        listCatalogModels({ model_kind: 'tts' }),
        listCatalogModels({ model_kind: 'embedding' }),
        listCatalogModels({ model_kind: 'rerank' }),
        listKnowledgeRerankers(),
        listKnowledgeEmbedders(),
        listCatalogProviders()
      ]);
      sections = prefsPayload.data.sections ?? [];
      promptDefaults = prefsPayload.data.prompt_defaults ?? {};
      fieldSchema = schemaPayload.ok ? (schemaPayload.data.fields ?? null) : null;
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
      embeddingCatalogOptions = embeddingPayload.data.models;
      embeddingLocalOptions = await listLocalCatalogModels('embedding');
      localEmbedders = localEmbedderPayload.data.local ?? [];
      catalogAllProviders = providersPayload.data;
      await activeProvidersStore.load({ silent: true });
      resumeRerankerPolling();
      resumeEmbedderPolling();
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
      catalogReloadBusy = false;
    }
  }

  async function savePreferences() {
    if (!draft || !baseline || !canSave) return;
    const edits = editsForSave(baseline, draft, effectiveFieldSchema);
    if (Object.keys(edits).length === 0) return;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      sections = payload.data.sections ?? [];
      promptDefaults = payload.data.prompt_defaults ?? promptDefaults;
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
    get promptDefaults() {
      return promptDefaults;
    },
    get fieldSchema() {
      // Live schema when loaded, else the committed mirror — so the Pref* field primitives keep
      // their bounds/hints even if GET /preferences/schema failed (never expose the raw null).
      return effectiveFieldSchema;
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
    get chatOptions() {
      return chatOptions;
    },
    get sttOptions() {
      return sttOptions;
    },
    get ttsOptions() {
      return ttsOptions;
    },
    get embeddingOptions() {
      // Merged (catalog + local) — the embedding picker lists both, like rerankers.
      return embeddingPickerOptions;
    },
    get localEmbedders() {
      return localEmbedders;
    },
    get embedderDownloading() {
      return embedderDownloading;
    },
    get embedderBusy() {
      return embedderBusy;
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
    setSectionError,
    setModelId,
    downloadReranker,
    cancelReranker,
    downloadEmbedder,
    cancelEmbedder,
    setDefaultTuningProfile,
    updateProfile,
    createProfile,
    duplicateProfile,
    deleteProfile,
    resetLockedProfile,
    saveProfileNow,
    saveDialogEdits,
    loadAll,
    reloadCatalog,
    savePreferences,
    resetDraft,
    abandonDraft
  };
}

export type PreferencesController = ReturnType<typeof createPreferencesController>;
