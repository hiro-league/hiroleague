import type { ChatChannelsTabPreference } from '$lib/preferences/keys';

export function normalizeChatChannelsTab(raw: string | null): ChatChannelsTabPreference | null {
  return raw === 'channels' || raw === 'messages' ? raw : null;
}
