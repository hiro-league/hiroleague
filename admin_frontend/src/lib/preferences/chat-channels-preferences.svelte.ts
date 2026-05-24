/**
 * Chat channels page tab + URL preferences (`?tab=` + optional `?channel_id=`).
 *
 * Tab handling uses `createTabPreferences` (Phase 2 §4a). The controller keeps
 * `selectedChannelId` runtime state and passes it into `setActiveTab` /
 * `syncNav` when the Messages tab is active.
 */
import { page } from '$app/state';
import { PREF_KEYS, type ChatChannelsTabPreference } from './keys';
import { createTabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly ChatChannelsTabPreference[] = ['channels', 'messages'] as const;

export type ChatChannelsPreferences = {
  readonly activeTab: ChatChannelsTabPreference;
  initialize: () => void;
  readChannelIdFromLocation: () => string | null;
  setActiveTab: (tab: ChatChannelsTabPreference, channelId?: string | null) => Promise<void>;
  syncNav: (channelId: string | null) => Promise<void>;
};

export function createChatChannelsPreferences(): ChatChannelsPreferences {
  const tabs = createTabPreferences<ChatChannelsTabPreference>({
    storageKey: PREF_KEYS.chatChannelsActiveTab,
    defaultTab: 'channels',
    allowed: ALLOWED,
    urlParamsToReset: ['channel_id'],
    omitDefaultFromUrl: true
  });

  function readChannelIdFromLocation(): string | null {
    return page.url.searchParams.get('channel_id')?.trim() || null;
  }

  function channelExtras(channelId: string | null | undefined): Record<string, string> {
    if (channelId?.trim()) {
      return { channel_id: channelId.trim() };
    }
    return {};
  }

  async function setActiveTab(
    tab: ChatChannelsTabPreference,
    channelId?: string | null
  ): Promise<void> {
    const extras = tab === 'messages' ? channelExtras(channelId) : {};
    await tabs.setActiveTab(tab, extras);
  }

  async function syncNav(channelId: string | null): Promise<void> {
    await setActiveTab(tabs.activeTab, channelId);
  }

  return {
    get activeTab() {
      return tabs.activeTab;
    },
    initialize: tabs.initialize,
    setActiveTab,
    syncNav,
    readChannelIdFromLocation
  };
}
