import { PREF_KEYS, type MemoriesTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly MemoriesTabPreference[] = ['memories', 'graph'] as const;

export type MemoriesTabPreferences = TabPreferences<MemoriesTabPreference>;

export function createMemoriesPreferences(): MemoriesTabPreferences {
  return createTabPreferences<MemoriesTabPreference>({
    storageKey: PREF_KEYS.memoriesActiveTab,
    defaultTab: 'memories',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}
