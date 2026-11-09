import { PREF_KEYS, type CatalogTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

// Phase 7b mockup: voices is a sub-tab of Profiles (with profiles and uses).
const ALLOWED: readonly CatalogTabPreference[] = ['providers', 'models', 'profiles', 'voices', 'uses'] as const;

export function createCatalogPreferences(): TabPreferences<CatalogTabPreference> {
  return createTabPreferences<CatalogTabPreference>({
    storageKey: PREF_KEYS.catalogActiveTab,
    defaultTab: 'providers',
    allowed: ALLOWED,
    urlParamsToReset: ['provider_id', 'model_kind', 'model_class', 'hosting', 'availability', 'sort', 'sort_dir']
  });
}
