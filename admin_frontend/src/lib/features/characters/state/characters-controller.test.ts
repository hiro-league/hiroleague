import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
import { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';

// --- Mocked collaborators (API layer + stores). characters-pure stays REAL so validation /
//     save-body construction is genuinely exercised. ---
const h = vi.hoisted(() => ({
  listCharacters: vi.fn(),
  getCharacter: vi.fn(),
  getCharacterResolved: vi.fn(),
  createCharacter: vi.fn(),
  updateCharacter: vi.fn(),
  deleteCharacter: vi.fn(),
  listCatalogModels: vi.fn(),
  listCatalogProviders: vi.fn(),
  getPreferences: vi.fn(),
  reloadCatalogAndRefetch: vi.fn()
}));

vi.mock('$lib/api/characters', () => ({
  listCharacters: (...a: unknown[]) => h.listCharacters(...a),
  getCharacter: (...a: unknown[]) => h.getCharacter(...a),
  getCharacterResolved: (...a: unknown[]) => h.getCharacterResolved(...a),
  createCharacter: (...a: unknown[]) => h.createCharacter(...a),
  updateCharacter: (...a: unknown[]) => h.updateCharacter(...a),
  deleteCharacter: (...a: unknown[]) => h.deleteCharacter(...a)
}));

vi.mock('$lib/api/catalog', () => ({
  listCatalogModels: (...a: unknown[]) => h.listCatalogModels(...a),
  listCatalogProviders: (...a: unknown[]) => h.listCatalogProviders(...a)
}));

vi.mock('$lib/api/preferences', () => ({
  getPreferences: (...a: unknown[]) => h.getPreferences(...a)
}));

vi.mock('$lib/catalog/catalog-reload', () => ({
  reloadCatalogAndRefetch: (...a: unknown[]) => h.reloadCatalogAndRefetch(...a),
  catalogReloadSuccessMessage: () => 'Catalog reloaded.'
}));

vi.mock('$lib/catalog/active-providers/active-providers-store.svelte', () => ({
  createActiveProvidersStore: () => ({
    load: vi.fn().mockResolvedValue(undefined),
    resolved: true,
    chatActiveProviderIds: new Set<string>(),
    ttsActiveProviderIds: new Set<string>()
  })
}));

vi.mock('$lib/features/characters/state/characters-photo-crop.svelte', () => ({
  createCharactersPhotoCrop: () => ({ pickPhoto: vi.fn(), submitPhoto: vi.fn() })
}));

import { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';

/** Minimal stateful stand-in for createCharactersPreferences (no URL/session side effects). */
function makePrefs(init: { activeTab?: string; detailMode?: string; characterId?: string | null } = {}) {
  let activeTab = init.activeTab ?? 'browse';
  let detailMode = init.detailMode ?? 'view';
  let characterId = init.characterId ?? null;
  return {
    get activeTab() {
      return activeTab;
    },
    get detailMode() {
      return detailMode;
    },
    get characterId() {
      return characterId;
    },
    initialize: vi.fn(),
    setState: vi.fn(async (tab: string, mode?: string, id?: string) => {
      activeTab = tab;
      if (mode !== undefined) detailMode = mode;
      characterId = id ?? null;
    })
  };
}

function setup(prefsInit?: Parameters<typeof makePrefs>[0]) {
  const prefs = makePrefs(prefsInit);
  const formApi = createCharactersFormModel();
  const notify = vi.fn();
  const confirmDiscard = vi.fn().mockResolvedValue(true);
  const ctrl = createCharactersPageController({
    prefs: prefs as unknown as ReturnType<typeof createCharactersPreferences>,
    formApi,
    notify,
    confirmDiscard
  });
  return { ctrl, prefs, formApi, notify, confirmDiscard };
}

beforeEach(() => {
  vi.clearAllMocks();
  h.listCharacters.mockResolvedValue({ data: [] });
  h.getCharacter.mockResolvedValue({ data: { id: 'ada', name: 'Ada' } });
  h.getCharacterResolved.mockResolvedValue({ data: { character_id: 'ada' } });
  h.createCharacter.mockResolvedValue({ data: { warnings: [], character: { id: 'ada' } } });
  h.updateCharacter.mockResolvedValue({ data: { warnings: [], character: { id: 'ada' } } });
  h.deleteCharacter.mockResolvedValue({ data: {} });
  h.listCatalogModels.mockResolvedValue({ data: { models: [] } });
  h.listCatalogProviders.mockResolvedValue({ data: [] });
  h.getPreferences.mockResolvedValue({
    data: { preferences: { tuning_profiles: {}, llm: { default_tuning_profile: 'balanced_chat' } } }
  });
  h.reloadCatalogAndRefetch.mockResolvedValue({ reload: {} });
});

describe('loadCharacters', () => {
  it('populates rows on success and clears loading/error', async () => {
    h.listCharacters.mockResolvedValueOnce({ data: [{ id: 'a', name: 'A' }] });
    const { ctrl } = setup();
    await ctrl.loadCharacters();
    expect(ctrl.rows).toHaveLength(1);
    expect(ctrl.loadingList).toBe(false);
    expect(ctrl.listError).toBeNull();
  });

  it('records listError and empties rows on failure', async () => {
    h.listCharacters.mockRejectedValueOnce(new Error('boom'));
    const { ctrl } = setup();
    await ctrl.loadCharacters();
    expect(ctrl.rows).toEqual([]);
    expect(ctrl.listError).toBe('boom');
  });
});

describe('openCharacterEdit', () => {
  it('loads detail, hydrates the form, and navigates to edit', async () => {
    h.getCharacter.mockResolvedValueOnce({ data: { id: 'a', name: 'A', llm_models: ['m1'] } });
    const { ctrl, prefs, formApi } = setup();
    await ctrl.openCharacterEdit({ id: 'a', name: 'A' });
    expect(ctrl.selected?.id).toBe('a');
    expect(formApi.form.new_id).toBe('a');
    expect(formApi.form.llm_models).toEqual(['m1']);
    expect(formApi.dirty).toBe(false);
    expect(prefs.setState).toHaveBeenCalledWith('detail', 'edit', 'a');
  });

  it('aborts when the unsaved-changes guard declines', async () => {
    const { ctrl, confirmDiscard, prefs } = setup();
    confirmDiscard.mockResolvedValueOnce(false);
    await ctrl.openCharacterEdit({ id: 'a', name: 'A' });
    expect(h.getCharacter).not.toHaveBeenCalled();
    expect(prefs.setState).not.toHaveBeenCalled();
  });
});

describe('saveCharacter', () => {
  it('blocks and notifies when the form is invalid', async () => {
    const { ctrl, notify } = setup({ activeTab: 'detail', detailMode: 'edit', characterId: null });
    await ctrl.saveCharacter();
    expect(notify).toHaveBeenCalledWith('error', 'Character id is required.');
    expect(h.createCharacter).not.toHaveBeenCalled();
    expect(h.updateCharacter).not.toHaveBeenCalled();
  });

  it('creates a new character when there is no persisted id', async () => {
    const { ctrl, formApi, notify, prefs } = setup({
      activeTab: 'detail',
      detailMode: 'edit',
      characterId: null
    });
    formApi.form = { ...formApi.form, new_id: 'ada', name: 'Ada' };
    await ctrl.saveCharacter();
    expect(h.createCharacter).toHaveBeenCalledTimes(1);
    expect(h.updateCharacter).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('success', 'Character saved.');
    expect(prefs.setState).toHaveBeenCalledWith('detail', 'edit', 'ada');
  });

  it('updates an existing character and surfaces backend warnings', async () => {
    h.updateCharacter.mockResolvedValueOnce({
      data: { warnings: ['heads up'], character: { id: 'ada' } }
    });
    const { ctrl, formApi, notify } = setup({
      activeTab: 'detail',
      detailMode: 'edit',
      characterId: 'ada'
    });
    formApi.form = { ...formApi.form, name: 'Ada' };
    await ctrl.saveCharacter();
    expect(h.updateCharacter).toHaveBeenCalledWith('ada', expect.any(Object));
    expect(h.createCharacter).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('warning', 'heads up');
    expect(notify).toHaveBeenCalledWith('success', 'Character saved.');
  });
});

describe('confirmDelete', () => {
  it('does nothing but close the dialog when the guard declines', async () => {
    const { ctrl, confirmDiscard } = setup({ characterId: 'ada' });
    confirmDiscard.mockResolvedValueOnce(false);
    ctrl.deleteOpen = true;
    await ctrl.confirmDelete();
    expect(h.deleteCharacter).not.toHaveBeenCalled();
    expect(ctrl.deleteOpen).toBe(false);
  });

  it('deletes, notifies, and returns to browse on confirm', async () => {
    const { ctrl, notify, prefs } = setup({
      activeTab: 'detail',
      detailMode: 'edit',
      characterId: 'ada'
    });
    await ctrl.confirmDelete();
    expect(h.deleteCharacter).toHaveBeenCalledWith('ada');
    expect(notify).toHaveBeenCalledWith('success', 'Character deleted.');
    expect(prefs.activeTab).toBe('browse');
  });
});

describe('reloadBundledCatalogInEditor', () => {
  it('notifies success and clears the busy flag', async () => {
    const { ctrl, notify } = setup();
    await ctrl.reloadBundledCatalogInEditor();
    expect(notify).toHaveBeenCalledWith('success', 'Catalog reloaded.');
    expect(ctrl.catalogReloadBusy).toBe(false);
  });

  it('notifies the error message when the reload fails', async () => {
    h.reloadCatalogAndRefetch.mockRejectedValueOnce(new Error('reload boom'));
    const { ctrl, notify } = setup();
    await ctrl.reloadBundledCatalogInEditor();
    expect(notify).toHaveBeenCalledWith('error', 'reload boom');
    expect(ctrl.catalogReloadBusy).toBe(false);
  });
});
