import {
  createCharacter,
  deleteCharacter,
  getCharacter,
  getCharacterResolved,
  listCharacters,
  updateCharacter,
  type CharacterDetail,
  type CharacterResolvedPayload,
  type CharacterRow
} from '$lib/api/characters';
import {
  listCatalogModels,
  listCatalogProviders,
  type CatalogModelRow,
  type CatalogProviderRow
} from '$lib/api/catalog';
import {
  catalogReloadSuccessMessage,
  reloadCatalogAndRefetch
} from '$lib/catalog/catalog-reload';
import { createActiveProvidersStore } from '$lib/catalog/active-providers/active-providers-store.svelte';
import { getPreferences, type TuningProfile } from '$lib/api/preferences';
import {
  characterSaveBody,
  emptyForm,
  formFromCharacter,
  mergeVoiceProviderDefaults,
  validateCharacterForm
} from '$lib/features/characters/utils';
import type { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
import type { createCharactersFormModel } from '$lib/features/characters/characters-form.svelte';
import { createCharactersPhotoCrop } from '$lib/features/characters/characters-photo-crop.svelte';

type NotifyKind = 'success' | 'error' | 'info' | 'warning';

/** Remote + catalog orchestration used by CharactersPage (delegates form UX to ``formApi``). */
export function createCharactersPageController(opts: {
  prefs: ReturnType<typeof createCharactersPreferences>;
  formApi: ReturnType<typeof createCharactersFormModel>;
  notify: (kind: NotifyKind, message: string) => void;
  confirmDiscard: () => Promise<boolean>;
}) {
  const { prefs, formApi, notify, confirmDiscard } = opts;
  const activeProvidersStore = createActiveProvidersStore();

  let rows = $state<CharacterRow[]>([]);
  let selected = $state<CharacterDetail | null>(null);
  let loadingList = $state(true);
  let loadingDetail = $state(false);
  let busy = $state(false);
  let listError = $state<string | null>(null);
  let detailError = $state<string | null>(null);
  let catalogReady = $state(false);
  let bundledCatalogReloadBusy = $state(false);
  let llmOptions = $state<CatalogModelRow[]>([]);
  let catalogAllProviders = $state<CatalogProviderRow[]>([]);
  let voiceOptions = $state<CatalogModelRow[]>([]);
  let catalogTtsProviders = $state<CatalogProviderRow[]>([]);
  let tuningProfiles = $state<Record<string, TuningProfile>>({});
  let workspaceDefaultTuningProfile = $state('balanced_chat');

  let deleteOpen = $state(false);
  let resolved = $state<CharacterResolvedPayload | null>(null);
  let resolvedError = $state<string | null>(null);

  async function loadResolvedConfig(id: string) {
    resolvedError = null;
    try {
      const payload = await getCharacterResolved(id);
      resolved = payload.data;
    } catch (err) {
      resolved = null;
      resolvedError =
        err instanceof Error ? err.message : 'Could not load resolved configuration.';
    }
  }

  async function loadCharacters() {
    loadingList = true;
    listError = null;
    try {
      const payload = await listCharacters();
      rows = payload.data;
    } catch (err) {
      rows = [];
      listError = err instanceof Error ? err.message : 'Failed to load characters.';
    } finally {
      loadingList = false;
    }
  }

  async function loadCatalogOptions(force = false) {
    if (catalogReady && !force) return;
    const [chat, tts, providers, preferences] = await Promise.all([
      listCatalogModels({ model_kind: 'chat' }),
      listCatalogModels({ model_kind: 'tts' }),
      listCatalogProviders(),
      getPreferences()
    ]);
    llmOptions = chat.data.models;
    catalogAllProviders = providers.data;
    voiceOptions = [...tts.data.models].sort((a, b) =>
      a.display_name.localeCompare(b.display_name)
    );
    catalogTtsProviders = providers.data.filter((p) => (p.tts_voices?.length ?? 0) > 0);
    tuningProfiles = preferences.data.preferences.tuning_profiles ?? {};
    workspaceDefaultTuningProfile =
      preferences.data.preferences.llm.default_tuning_profile || 'balanced_chat';
    await activeProvidersStore.load({ silent: true });
    if (!activeProvidersStore.resolved) {
      console.warn(
        '⚠️ Characters editor — workspace active providers unavailable · inactive-picker styling skipped'
      );
    }
    catalogReady = true;
  }

  function setTtsVoicePreset(providerId: string, voiceId: string) {
    formApi.form = {
      ...formApi.form,
      tts_voice_by_provider: { ...formApi.form.tts_voice_by_provider, [providerId]: voiceId }
    };
    formApi.markDirty();
  }

  async function reloadBundledCatalogInEditor() {
    bundledCatalogReloadBusy = true;
    try {
      const result = await reloadCatalogAndRefetch(['chat', 'tts']);
      catalogReady = false;
      await loadCatalogOptions(true);
      formApi.form.tts_voice_by_provider = mergeVoiceProviderDefaults(
        formApi.form.tts_voice_by_provider,
        catalogTtsProviders
      );
      notify('success', catalogReloadSuccessMessage(result.reload));
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      bundledCatalogReloadBusy = false;
    }
  }

  async function loadDetail(id: string, mode: 'view' | 'edit') {
    loadingDetail = true;
    detailError = null;
    try {
      if (mode === 'edit') await loadCatalogOptions();
      const payload = await getCharacter(id);
      selected = payload.data;
      if (mode === 'edit') {
        formApi.form = formFromCharacter(payload.data);
        formApi.form.tts_voice_by_provider = mergeVoiceProviderDefaults(
          formApi.form.tts_voice_by_provider,
          catalogTtsProviders
        );
        formApi.dirty = false;
        formApi.resetOrderedModelPickersNonce();
      }
      await loadResolvedConfig(id);
    } catch (err) {
      selected = null;
      resolved = null;
      resolvedError = null;
      detailError = err instanceof Error ? err.message : 'Failed to load character.';
    } finally {
      loadingDetail = false;
    }
  }

  async function openBrowse() {
    if (!(await confirmDiscard())) return;
    selected = null;
    resolved = null;
    resolvedError = null;
    formApi.dirty = false;
    await prefs.setState('browse');
    await loadCharacters();
  }

  async function openCharacterEdit(row: CharacterRow) {
    if (!(await confirmDiscard())) return;
    formApi.dirty = false;
    await prefs.setState('detail', 'edit', row.id);
    await loadDetail(row.id, 'edit');
  }

  async function openNewCharacter() {
    if (!(await confirmDiscard())) return;
    await loadCatalogOptions();
    selected = null;
    resolved = null;
    resolvedError = null;
    formApi.form = emptyForm();
    formApi.form.tts_voice_by_provider = mergeVoiceProviderDefaults({}, catalogTtsProviders);
    formApi.resetOrderedModelPickersNonce();
    formApi.dirty = false;
    await prefs.setState('detail', 'edit');
  }

  async function enterEditMode() {
    if (!prefs.characterId) return;
    await prefs.setState('detail', 'edit', prefs.characterId);
    await loadDetail(prefs.characterId, 'edit');
  }

  async function cancelEdit() {
    if (!(await confirmDiscard())) return;
    formApi.dirty = false;
    if (prefs.characterId) {
      await prefs.setState('detail', 'view', prefs.characterId);
      await loadDetail(prefs.characterId, 'view');
    } else {
      await openBrowse();
    }
  }

  async function saveCharacter() {
    const invalid = validateCharacterForm(prefs.characterId, formApi.form);
    if (invalid) {
      notify('error', invalid);
      return;
    }
    busy = true;
    try {
      const id = prefs.characterId;
      const body = characterSaveBody(prefs.characterId, formApi.form);
      const payload = id ? await updateCharacter(id, body) : await createCharacter(body);
      for (const warning of payload.data.warnings) notify('warning', warning);
      const savedId = payload.data.character.id;
      notify('success', 'Character saved.');
      formApi.dirty = false;
      await prefs.setState('detail', 'edit', savedId);
      await loadCharacters();
      await loadDetail(savedId, 'edit');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  async function confirmDelete() {
    if (!prefs.characterId) return;
    if (!(await confirmDiscard())) {
      // User chose to stay and keep editing — closing delete dialog matches "continue editing" semantics.
      deleteOpen = false;
      return;
    }
    busy = true;
    try {
      await deleteCharacter(prefs.characterId);
      notify('success', 'Character deleted.');
      deleteOpen = false;
      await openBrowse();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Delete failed.');
    } finally {
      busy = false;
    }
  }

  function isCharactersPath(pathname: string): boolean {
    return pathname.endsWith('/characters') || pathname.endsWith('/characters/');
  }

  /** Apply URL + prefs to remote state + optional edit form. */
  async function hydrateCharactersFromUrl() {
    prefs.initialize();
    await loadCharacters();
    if (prefs.activeTab === 'browse') {
      selected = null;
      resolved = null;
      resolvedError = null;
      formApi.dirty = false;
      return;
    }
    if (prefs.activeTab === 'detail') {
      if (prefs.characterId) {
        await loadDetail(prefs.characterId, prefs.detailMode);
      } else if (prefs.detailMode === 'edit') {
        await loadCatalogOptions();
        selected = null;
        resolved = null;
        resolvedError = null;
        formApi.form = emptyForm();
        formApi.form.tts_voice_by_provider = mergeVoiceProviderDefaults({}, catalogTtsProviders);
        formApi.dirty = false;
        formApi.resetOrderedModelPickersNonce();
      }
    }
  }

  function charactersUrlHasDetailParams(searchParams: URLSearchParams): boolean {
    return (
      searchParams.has('tab') ||
      searchParams.has('mode') ||
      searchParams.has('character_id')
    );
  }

  const photoCrop = createCharactersPhotoCrop({
    getCharacterId: () => (prefs.characterId ?? '').trim(),
    notify,
    setBusy: (v: boolean) => {
      busy = v;
    },
    onAfterPhotoUpload: async () => {
      await loadCharacters();
      const id = (prefs.characterId ?? '').trim();
      if (id) await loadDetail(id, prefs.detailMode);
    }
  });

  return {
    get rows(): CharacterRow[] {
      return rows;
    },
    get selected(): CharacterDetail | null {
      return selected;
    },
    get loadingList(): boolean {
      return loadingList;
    },
    get loadingDetail(): boolean {
      return loadingDetail;
    },
    get busy(): boolean {
      return busy;
    },
    get listError(): string | null {
      return listError;
    },
    get detailError(): string | null {
      return detailError;
    },
    get llmOptions(): CatalogModelRow[] {
      return llmOptions;
    },
    get catalogAllProviders(): CatalogProviderRow[] {
      return catalogAllProviders;
    },
    get voiceOptions(): CatalogModelRow[] {
      return voiceOptions;
    },
    get catalogTtsProviders(): CatalogProviderRow[] {
      return catalogTtsProviders;
    },
    get workspaceActiveProvidersResolved(): boolean {
      return activeProvidersStore.resolved;
    },
    /** Getters unwrap plain ``Set``/rows for picker props — raw ``$derived`` fields on POJO controllers confuse prop bridging and produced empty lookups (all offline). */
    get workspaceChatActiveIds(): Set<string> {
      return activeProvidersStore.chatActiveProviderIds;
    },
    get workspaceTtsActiveIds(): Set<string> {
      return activeProvidersStore.ttsActiveProviderIds;
    },
    get tuningProfiles(): Record<string, TuningProfile> {
      return tuningProfiles;
    },
    get workspaceDefaultTuningProfile(): string {
      return workspaceDefaultTuningProfile;
    },
    get resolved(): CharacterResolvedPayload | null {
      return resolved;
    },
    get resolvedError(): string | null {
      return resolvedError;
    },
    get ttsPresetGoogle(): CatalogProviderRow | null {
      return catalogTtsProviders.find((p) => p.id === 'google') ?? null;
    },
    get ttsPresetOpenai(): CatalogProviderRow | null {
      return catalogTtsProviders.find((p) => p.id === 'openai') ?? null;
    },
    get ttsPresetOtherProviders(): CatalogProviderRow[] {
      return catalogTtsProviders.filter((p) => p.id !== 'google' && p.id !== 'openai');
    },

    get catalogReloadBusy(): boolean {
      return bundledCatalogReloadBusy;
    },

    // modals/actions
    get deleteOpen(): boolean {
      return deleteOpen;
    },
    set deleteOpen(open: boolean) {
      deleteOpen = open;
    },
    loadCharacters,
    openBrowse,
    openCharacterEdit,
    openNewCharacter,
    enterEditMode,
    cancelEdit,
    saveCharacter,
    confirmDelete,
    reloadBundledCatalogInEditor,
    setTtsVoicePreset,
    pickPhoto: photoCrop.pickPhoto,
    submitPhoto: photoCrop.submitPhoto,

    get cropOpen(): boolean {
      return photoCrop.cropOpen;
    },
    set cropOpen(open: boolean) {
      photoCrop.cropOpen = open;
    },

    handleCropZoom: photoCrop.handleCropZoom,
    handleCropPanX: photoCrop.handleCropPanX,
    handleCropPanY: photoCrop.handleCropPanY,
    handleCropCanvas: photoCrop.handleCropCanvas,

    get cropZoom(): number {
      return photoCrop.cropZoom;
    },
    set cropZoom(v: number) {
      photoCrop.cropZoom = v;
    },
    get cropX(): number {
      return photoCrop.cropX;
    },
    set cropX(v: number) {
      photoCrop.cropX = v;
    },
    get cropY(): number {
      return photoCrop.cropY;
    },
    set cropY(v: number) {
      photoCrop.cropY = v;
    },
    dismissCropModal: photoCrop.dismissCropModal,

    hydrateCharactersFromUrl,
    charactersUrlHasDetailParams,
    isCharactersPath
  };
}
