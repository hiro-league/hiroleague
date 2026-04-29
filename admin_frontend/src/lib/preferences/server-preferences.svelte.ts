import { goto } from '$app/navigation';
import { page } from '$app/state';
import { PREF_KEYS, type ServerTabPreference } from './keys';
import { readSessionString, writeSessionString } from './storage';

function normalizeTab(raw: string | null): ServerTabPreference | null {
  return raw === 'workspaces' || raw === 'gateways' ? raw : null;
}

export function createServerPreferences() {
  let activeTab = $state<ServerTabPreference>('workspaces');

  function initialize() {
    activeTab =
      normalizeTab(page.url.searchParams.get('tab')) ??
      normalizeTab(readSessionString(PREF_KEYS.serverActiveTab)) ??
      'workspaces';
  }

  async function setActiveTab(tab: ServerTabPreference) {
    activeTab = tab;
    writeSessionString(PREF_KEYS.serverActiveTab, tab);

    const nextUrl = new URL(page.url);
    nextUrl.searchParams.set('tab', tab);
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
