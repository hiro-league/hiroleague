import { goto } from '$app/navigation';
import { page } from '$app/state';
import { PREF_KEYS, type CharactersTabPreference } from './keys';
import { readSessionString, writeSessionString } from './storage';

type DetailMode = 'view' | 'edit';

function normalizeTab(raw: string | null): CharactersTabPreference | null {
  return raw === 'browse' || raw === 'detail' ? raw : null;
}

function normalizeMode(raw: string | null): DetailMode {
  return raw === 'edit' ? 'edit' : 'view';
}

export function createCharactersPreferences() {
  let activeTab = $state<CharactersTabPreference>('browse');
  let detailMode = $state<DetailMode>('view');
  let characterId = $state('');

  function initialize() {
    const params = page.url.searchParams;
    // Sidebar link is `/characters/` with no query — always land on Browse (session alone must not keep Detail).
    const hasCharactersParams =
      params.has('tab') || params.has('mode') || params.has('character_id');

    if (!hasCharactersParams) {
      activeTab = 'browse';
      detailMode = 'view';
      characterId = '';
      writeSessionString(PREF_KEYS.charactersActiveTab, activeTab);
      return;
    }

    const urlTab = normalizeTab(params.get('tab'));
    const storedTab = normalizeTab(readSessionString(PREF_KEYS.charactersActiveTab));
    const nextMode = normalizeMode(params.get('mode'));
    const nextId = params.get('character_id') ?? '';

    activeTab = urlTab ?? storedTab ?? 'browse';
    detailMode = nextMode;
    characterId = nextId;
    if (activeTab === 'detail' && !characterId && detailMode === 'view') {
      activeTab = 'browse';
    }
    writeSessionString(PREF_KEYS.charactersActiveTab, activeTab);
  }

  async function setState(tab: CharactersTabPreference, mode: DetailMode = 'view', id = '') {
    activeTab = tab;
    detailMode = mode;
    characterId = id;
    writeSessionString(PREF_KEYS.charactersActiveTab, tab);

    const nextUrl = new URL(page.url);
    nextUrl.searchParams.set('tab', tab);
    nextUrl.searchParams.delete('mode');
    nextUrl.searchParams.delete('character_id');
    if (tab === 'detail') {
      nextUrl.searchParams.set('mode', mode);
      if (id) nextUrl.searchParams.set('character_id', id);
    }
    await goto(`${nextUrl.pathname}${nextUrl.search}`, {
      keepFocus: true,
      noScroll: true,
      replaceState: true
    });
  }

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
    initialize,
    setState
  };
}
