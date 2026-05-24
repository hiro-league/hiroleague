import { PREF_KEYS, type ChannelsDevicesTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly ChannelsDevicesTabPreference[] = ['channels', 'devices'] as const;

export function createChannelsDevicesPreferences(): TabPreferences<ChannelsDevicesTabPreference> {
  return createTabPreferences<ChannelsDevicesTabPreference>({
    storageKey: PREF_KEYS.channelsDevicesActiveTab,
    defaultTab: 'channels',
    allowed: ALLOWED
  });
}
