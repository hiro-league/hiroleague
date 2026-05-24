/**
 * Characters page preferences. Tab handling is delegated to
 * `createTabPreferences`; `detailMode` and `characterId` are
 * Characters-specific extra state kept alongside.
 *
 * The page also has the "land on Browse when the route arrives with no query
 * params" rule (`/characters/` from the sidebar should not restore Detail
 * from session alone). That rule is preserved in `initialize()` below.
 */
import { page } from '$app/state';
import { PREF_KEYS, type CharactersTabPreference } from './keys';
import { writeSessionString } from './storage';
import { createTabPreferences } from './create-tab-preferences.svelte';

type DetailMode = 'view' | 'edit';

const ALLOWED: readonly CharactersTabPreference[] = ['browse', 'detail'] as const;

export function createCharactersPreferences() {
  const tabs = createTabPreferences<CharactersTabPreference>({
    storageKey: PREF_KEYS.charactersActiveTab,
    defaultTab: 'browse',
    allowed: ALLOWED,
    urlParamsToReset: ['mode', 'character_id']
  });

  let detailMode = $state<DetailMode>('view');
  let characterId = $state('');

  function initialize() {
    const params = page.url.searchParams;
    const hasCharactersParams =
      params.has('tab') || params.has('mode') || params.has('character_id');

    if (!hasCharactersParams) {
      writeSessionString(PREF_KEYS.charactersActiveTab, 'browse');
      detailMode = 'view';
      characterId = '';
      tabs.initialize();
      return;
    }

    detailMode = params.get('mode') === 'edit' ? 'edit' : 'view';
    characterId = params.get('character_id') ?? '';
    tabs.initialize();

    if (tabs.activeTab === 'detail' && !characterId && detailMode === 'view') {
      void tabs.setActiveTab('browse');
    }
  }

  async function setState(
    tab: CharactersTabPreference,
    mode: DetailMode = 'view',
    id = ''
  ) {
    detailMode = mode;
    characterId = id;
    const extras: Record<string, string> = {};
    if (tab === 'detail') {
      extras.mode = mode;
      if (id) extras.character_id = id;
    }
    await tabs.setActiveTab(tab, extras);
  }

  return {
    get activeTab() {
      return tabs.activeTab;
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
