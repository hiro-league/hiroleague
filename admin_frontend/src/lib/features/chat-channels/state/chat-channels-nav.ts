/**
 * Chat channels URL + session prefs (hydrate / persist).
 * Plain TS keeps ``$app`` usage to ``goto`` only; callers pass ``page.url`` / ``searchParams``.
 */
import { goto } from '$app/navigation';
import type { ChatChannelsTabPreference } from '$lib/preferences/keys';
import { PREF_KEYS } from '$lib/preferences/keys';
import { readSessionString, writeSessionString } from '$lib/preferences/storage';
import { normalizeChatChannelsTab } from '$lib/features/chat-channels/shared/chat-channel-tab';

/** Reads ``?tab`` / ``?channel_id`` plus session fallback (single place for shell restore). */
export function readChatChannelsNavFromLocation(searchParams: URLSearchParams): {
  tab: ChatChannelsTabPreference;
  channelId: string | null;
} {
  const sessionTabRaw = readSessionString(PREF_KEYS.chatChannelsActiveTab);
  const tab =
    normalizeChatChannelsTab(searchParams.get('tab')) ??
    normalizeChatChannelsTab(sessionTabRaw) ??
    'channels';
  const channelId = searchParams.get('channel_id');
  return { tab, channelId };
}

/** Session tab prefs + shallow replaceState merge (matches prior ``syncUrl`` behaviour). */
export async function persistChatChannelsNavToUrl(
  currentUrl: URL,
  activeTab: ChatChannelsTabPreference,
  selectedChannelId: string | null
): Promise<void> {
  writeSessionString(PREF_KEYS.chatChannelsActiveTab, activeTab);

  const nextUrl = new URL(currentUrl);
  nextUrl.searchParams.set('tab', activeTab);
  if (activeTab === 'messages' && selectedChannelId) {
    nextUrl.searchParams.set('channel_id', selectedChannelId);
  } else {
    nextUrl.searchParams.delete('channel_id');
  }

  await goto(`${nextUrl.pathname}${nextUrl.search}`, {
    keepFocus: true,
    noScroll: true,
    replaceState: true
  });
}
