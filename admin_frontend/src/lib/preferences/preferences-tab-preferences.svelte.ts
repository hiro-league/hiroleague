import type { PreferenceTabId } from '$lib/features/preferences/shared/preferences-tabs';
import { DEFAULT_PREFERENCE_TAB } from '$lib/features/preferences/shared/preferences-tabs';
import { PREF_KEYS, type PreferencesTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly PreferencesTabPreference[] = [
  'models',
  'media',
  'memory',
  'knowledge',
  'tuning-profiles'
] as const;

export function createPreferencesTabPreferences(): TabPreferences<PreferencesTabPreference> {
  return createTabPreferences<PreferencesTabPreference>({
    storageKey: PREF_KEYS.preferencesActiveTab,
    defaultTab: DEFAULT_PREFERENCE_TAB,
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}

export type { PreferenceTabId };
