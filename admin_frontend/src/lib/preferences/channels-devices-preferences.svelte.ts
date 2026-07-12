import { PREF_KEYS, type ChannelsDevicesTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';
import { isFeatureActive } from '$lib/shell/features';

// `devices` is only selectable while the Devices feature is active — a hidden `?tab=devices` then
// fails validation in `normalise` and falls back to the default (Channels) tab.
const ALLOWED: readonly ChannelsDevicesTabPreference[] = [
  'channels',
  ...(isFeatureActive('devices') ? (['devices'] as const) : [])
];

export function createChannelsDevicesPreferences(): TabPreferences<ChannelsDevicesTabPreference> {
  return createTabPreferences<ChannelsDevicesTabPreference>({
    storageKey: PREF_KEYS.channelsDevicesActiveTab,
    defaultTab: 'channels',
    allowed: ALLOWED
  });
}
