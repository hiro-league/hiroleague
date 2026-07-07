import type { PreferenceTabId } from '$lib/features/preferences/shared/preferences-tabs';
import {
  DEFAULT_PREFERENCE_TAB,
  VISIBLE_PREFERENCE_TABS,
  migrateLegacyPreferenceHash
} from '$lib/features/preferences/shared/preferences-tabs';
import { PREF_KEYS, type PreferencesTabPreference } from './keys';
import { createTabPreferences } from './create-tab-preferences.svelte';

// Only visible tabs are selectable — a hidden feature's tab id (e.g. `?tab=eval` when Eval is off)
// fails validation in `normalise` and falls back to the default tab.
const ALLOWED: readonly PreferencesTabPreference[] = VISIBLE_PREFERENCE_TABS.map(
  (tab) => tab.id
) as readonly PreferencesTabPreference[];

export function createPreferencesTabPreferences() {
  const tabs = createTabPreferences<PreferencesTabPreference>({
    storageKey: PREF_KEYS.preferencesActiveTab,
    defaultTab: DEFAULT_PREFERENCE_TAB,
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });

  // Delegate via a getter — spreading `{ ...tabs }` would snapshot the `activeTab`
  // getter into a static value and break $state reactivity (tab strip would freeze).
  return {
    get activeTab() {
      return tabs.activeTab;
    },
    initialize: tabs.initialize,
    setActiveTab: tabs.setActiveTab,
    syncActiveTabFromUrl: tabs.syncActiveTabFromUrl,
    /** Resolve legacy hash + URL/session tab before first paint. */
    bootstrap() {
      migrateLegacyPreferenceHash();
      tabs.initialize();
    }
  };
}

export type PreferencesTabPreferences = ReturnType<typeof createPreferencesTabPreferences>;

export type { PreferenceTabId };
