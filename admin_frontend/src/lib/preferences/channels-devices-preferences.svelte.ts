import { goto } from '$app/navigation';
import { page } from '$app/state';
import { PREF_KEYS, type ChannelsDevicesTabPreference } from './keys';
import { readSessionString, writeSessionString } from './storage';

function normalizeTab(raw: string | null): ChannelsDevicesTabPreference | null {
  return raw === 'channels' || raw === 'devices' ? raw : null;
}

export function createChannelsDevicesPreferences() {
  let activeTab = $state<ChannelsDevicesTabPreference>('channels');

  function initialize() {
    activeTab =
      normalizeTab(page.url.searchParams.get('tab')) ??
      normalizeTab(readSessionString(PREF_KEYS.channelsDevicesActiveTab)) ??
      'channels';
  }

  async function setActiveTab(tab: ChannelsDevicesTabPreference) {
    activeTab = tab;
    writeSessionString(PREF_KEYS.channelsDevicesActiveTab, tab);

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
