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
import { listCatalogModels, listCatalogProviders } from '$lib/api/catalog';
import { getPreferences } from '$lib/api/preferences';
import { aiProfileLine, isPlanModel, voiceProfileLine } from '$lib/catalog/hiro-jobs';
import { catalogModelNamer } from '$lib/catalog/model-namer';
import {
  characterSaveBody,
  emptyForm,
  formFromCharacter,
  validateCharacterForm
} from '$lib/features/characters/shared/characters-pure';
import type { ProfileOption } from '$lib/features/characters/shared/profile-option';
import type { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
import type { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';
import { createCharactersPhotoCrop } from '$lib/features/characters/state/characters-photo-crop.svelte';

type NotifyKind = 'success' | 'error' | 'info' | 'warning';

/** Remote orchestration used by CharactersPage (delegates form UX to ``formApi``). Phase 7b step 5: the
 *  editor's lists pick from the workspace's AI and voice profiles (read from preferences, named with the
 *  catalog), replacing the catalog model pickers, the tuning profile and the TTS voice presets. */
export function createCharactersPageController(opts: {
  prefs: ReturnType<typeof createCharactersPreferences>;
  formApi: ReturnType<typeof createCharactersFormModel>;
  notify: (kind: NotifyKind, message: string) => void;
  confirmDiscard: () => Promise<boolean>;
}) {
  const { prefs, formApi, notify, confirmDiscard } = opts;

  let rows = $state<CharacterRow[]>([]);
  let selected = $state<CharacterDetail | null>(null);
  let loadingList = $state(true);
  let loadingDetail = $state(false);
  let busy = $state(false);
  let listError = $state<string | null>(null);
  let detailError = $state<string | null>(null);
  let profilesReady = $state(false);
  let aiProfileOptions = $state<ProfileOption[]>([]);
  let voiceProfileOptions = $state<ProfileOption[]>([]);

  let deleteOpen = $state(false);
  let resolved = $state<CharacterResolvedPayload | null>(null);
  let resolvedError = $state<string | null>(null);

  async function loadResolvedConfig(id: string) {
    resolvedError = null;
    try {
      const payload = await getCharacterResolved(id);
      resolved = payload;
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
      rows = payload;
    } catch (err) {
      rows = [];
      listError = err instanceof Error ? err.message : 'Failed to load characters.';
    } finally {
      loadingList = false;
    }
  }

  /** The workspace's AI and voice profiles for the editor's two lists, each with a one-line summary
   *  (catalog names for the model and provider). A plan tool's profile is offered but flagged: chat
   *  skips it (it isn't a chat model). */
  async function loadProfileOptions(force = false) {
    if (profilesReady && !force) return;
    const [chat, tts, providers, preferences] = await Promise.all([
      listCatalogModels({ model_kind: 'chat' }),
      listCatalogModels({ model_kind: 'tts' }),
      listCatalogProviders(),
      getPreferences()
    ]);
    const namer = catalogModelNamer([...chat.models, ...tts.models], providers);
    const saved = preferences.preferences;
    const byLabel = (a: ProfileOption, b: ProfileOption) => a.label.localeCompare(b.label);
    aiProfileOptions = Object.entries(saved.ai?.profiles ?? {})
      .map(([id, p]) => ({
        id,
        label: p.label,
        line: aiProfileLine(p, namer),
        note: isPlanModel(p.model) ? "A plan tool's model: chat skips it." : null
      }))
      .sort(byLabel);
    voiceProfileOptions = Object.entries(saved.voice?.profiles ?? {})
      .map(([id, p]) => ({ id, label: p.label, line: voiceProfileLine(p, namer), note: null }))
      .sort(byLabel);
    profilesReady = true;
  }

  async function loadDetail(id: string, mode: 'view' | 'edit') {
    loadingDetail = true;
    detailError = null;
    try {
      if (mode === 'edit') await loadProfileOptions();
      const payload = await getCharacter(id);
      selected = payload;
      if (mode === 'edit') {
        formApi.form = formFromCharacter(payload);
        formApi.dirty = false;
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
    await loadProfileOptions();
    selected = null;
    resolved = null;
    resolvedError = null;
    formApi.form = emptyForm();
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
      for (const warning of payload.warnings) notify('warning', warning);
      const savedId = payload.character.id;
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
    // Step 1d: pages have no trailing slash.
    return pathname.endsWith('/characters');
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
        await loadProfileOptions();
        selected = null;
        resolved = null;
        resolvedError = null;
        formApi.form = emptyForm();
        formApi.dirty = false;
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
    /** The workspace's AI profiles (by name) for the character's AI list. */
    get aiProfileOptions(): ProfileOption[] {
      return aiProfileOptions;
    },
    /** The workspace's voice profiles (by name) for the character's voice list. */
    get voiceProfileOptions(): ProfileOption[] {
      return voiceProfileOptions;
    },
    get resolved(): CharacterResolvedPayload | null {
      return resolved;
    },
    get resolvedError(): string | null {
      return resolvedError;
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
    /** Re-read the profiles (after editing them in Catalog → Profiles in another tab). */
    reloadProfileOptions: () => loadProfileOptions(true),

    /** Photo-crop sub-controller (pickPhoto/submitPhoto/crop state) — consumed directly by the dialogs. */
    get photoCrop() {
      return photoCrop;
    },

    hydrateCharactersFromUrl,
    charactersUrlHasDetailParams,
    isCharactersPath
  };
}
