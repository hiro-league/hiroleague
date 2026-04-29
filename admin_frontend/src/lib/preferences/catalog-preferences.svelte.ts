import { goto } from '$app/navigation';
import { page } from '$app/state';
import { PREF_KEYS, type CatalogTabPreference } from './keys';
import { readSessionString, writeSessionString } from './storage';

function normalizeTab(raw: string | null): CatalogTabPreference | null {
  return raw === 'providers' || raw === 'models' || raw === 'active-providers' ? raw : null;
}

export function createCatalogPreferences() {
  let activeTab = $state<CatalogTabPreference>('providers');

  function initialize() {
    activeTab =
      normalizeTab(page.url.searchParams.get('tab')) ??
      normalizeTab(readSessionString(PREF_KEYS.catalogActiveTab)) ??
      'providers';
  }

  async function setActiveTab(tab: CatalogTabPreference, params: Record<string, string> = {}) {
    activeTab = tab;
    writeSessionString(PREF_KEYS.catalogActiveTab, tab);

    const nextUrl = new URL(page.url);
    nextUrl.searchParams.set('tab', tab);
    for (const key of ['provider_id', 'model_kind', 'model_class', 'hosting']) {
      nextUrl.searchParams.delete(key);
    }
    for (const [key, value] of Object.entries(params)) {
      if (value.trim()) {
        nextUrl.searchParams.set(key, value);
      }
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
    initialize,
    setActiveTab
  };
}
