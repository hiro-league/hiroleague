import { PREF_KEYS, type ServerTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';
import { isFeatureActive } from '$lib/shell/features';

// `metrics` is only selectable while the Metrics feature is active — a hidden `?tab=metrics` then
// fails validation in `normalise` and falls back to the default (Workspaces) tab.
const ALLOWED: readonly ServerTabPreference[] = [
  'workspaces',
  'gateways',
  ...(isFeatureActive('metrics') ? (['metrics'] as const) : [])
];

export function createServerPreferences(): TabPreferences<ServerTabPreference> {
  return createTabPreferences<ServerTabPreference>({
    storageKey: PREF_KEYS.serverActiveTab,
    defaultTab: 'workspaces',
    allowed: ALLOWED
  });
}
