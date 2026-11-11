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
  getPreferences: vi.fn()
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
  h.listCharacters.mockResolvedValue([]);
  h.getCharacter.mockResolvedValue({ id: 'ada', name: 'Ada' });
  h.getCharacterResolved.mockResolvedValue({ character_id: 'ada' });
  h.createCharacter.mockResolvedValue({ warnings: [], character: { id: 'ada' } });
  h.updateCharacter.mockResolvedValue({ warnings: [], character: { id: 'ada' } });
  h.deleteCharacter.mockResolvedValue({});
  h.listCatalogModels.mockResolvedValue({ models: [] });
  h.listCatalogProviders.mockResolvedValue([]);
  // Phase 7b step 5: the editor's lists pick from the workspace's AI and voice profiles.
  h.getPreferences.mockResolvedValue({
      preferences: {
        ai: {
          profiles: {
            'hiro-chat': { label: "Hiro's chat", model: 'google:gemini-flash', temperature: 0.3, max_tokens: 2048, thinking: null },
            'on-codex': { label: 'On Codex', model: 'codex:gpt-5', temperature: null, max_tokens: null, thinking: null },
            'a-claude': { label: 'A Claude', model: 'anthropic:claude-sonnet', temperature: 0.2, max_tokens: 1600, thinking: 'low' }
          }
        },
        voice: {
          profiles: {
            'hiro-voice': { label: "Hiro's voice", model: 'openai:gpt-4o-mini-tts', voice: 'sage', voice_label: '', style: '', speed: 1 }
          }
        }
      }
    });
});

describe('loadCharacters', () => {
  it('populates rows on success and clears loading/error', async () => {
    h.listCharacters.mockResolvedValueOnce([{ id: 'a', name: 'A' }]);
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
    h.getCharacter.mockResolvedValueOnce({ id: 'a', name: 'A', ai_profiles: ['a-claude'], voice_profiles: ['hiro-voice'] });
    const { ctrl, prefs, formApi } = setup();
    await ctrl.openCharacterEdit({ id: 'a', name: 'A' });
    expect(ctrl.selected?.id).toBe('a');
    expect(formApi.form.new_id).toBe('a');
    expect(formApi.form.ai_profiles).toEqual(['a-claude']);
    expect(formApi.form.voice_profiles).toEqual(['hiro-voice']);
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
    h.updateCharacter.mockResolvedValueOnce({ warnings: ['heads up'], character: { id: 'ada' } });
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

describe('profile options (Phase 7b step 5)', () => {
  it('lists the AI and voice profiles by name with a one-line summary, flagging plan-tool models', async () => {
    const { ctrl } = setup();
    await ctrl.openNewCharacter();
    expect(ctrl.aiProfileOptions.map((o) => o.id)).toEqual(['a-claude', 'hiro-chat', 'on-codex']);
    const chat = ctrl.aiProfileOptions.find((o) => o.id === 'hiro-chat');
    expect(chat?.line).toBe('google · gemini-flash · temperature 0.3 · 2,048 tokens · thinking: model default');
    expect(chat?.note).toBeNull();
    expect(ctrl.aiProfileOptions.find((o) => o.id === 'on-codex')?.note).toMatch(/plan tool/);
    expect(ctrl.voiceProfileOptions).toEqual([
      { id: 'hiro-voice', label: "Hiro's voice", line: 'openai · gpt-4o-mini-tts · sage', note: null }
    ]);
  });

  it('reads the profiles again on reload (after an edit in Catalog → Profiles)', async () => {
    const { ctrl } = setup();
    await ctrl.openNewCharacter();
    expect(h.getPreferences).toHaveBeenCalledTimes(1);
    await ctrl.openNewCharacter();
    expect(h.getPreferences).toHaveBeenCalledTimes(1); // cached
    await ctrl.reloadProfileOptions();
    expect(h.getPreferences).toHaveBeenCalledTimes(2);
  });

  it('saves the ordered lists as ai_profiles_json / voice_profiles_json', async () => {
    const { ctrl, formApi } = setup({ activeTab: 'detail', detailMode: 'edit', characterId: 'ada' });
    formApi.form = { ...formApi.form, name: 'Ada', ai_profiles: ['a-claude', 'hiro-chat'], voice_profiles: [] };
    await ctrl.saveCharacter();
    const body = h.updateCharacter.mock.calls[0][1];
    expect(body.ai_profiles_json).toBe('["a-claude","hiro-chat"]');
    expect(body.voice_profiles_json).toBe('[]');
  });
});
