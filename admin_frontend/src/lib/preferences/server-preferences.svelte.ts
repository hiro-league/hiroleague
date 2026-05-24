import { PREF_KEYS, type ServerTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly ServerTabPreference[] = ['workspaces', 'gateways'] as const;

export function createServerPreferences(): TabPreferences<ServerTabPreference> {
  return createTabPreferences<ServerTabPreference>({
    storageKey: PREF_KEYS.serverActiveTab,
    defaultTab: 'workspaces',
    allowed: ALLOWED
  });
}
