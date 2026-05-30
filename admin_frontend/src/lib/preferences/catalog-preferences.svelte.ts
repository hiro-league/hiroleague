import { PREF_KEYS, type CatalogTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly CatalogTabPreference[] = ['active-providers', 'providers', 'models'] as const;

export function createCatalogPreferences(): TabPreferences<CatalogTabPreference> {
  return createTabPreferences<CatalogTabPreference>({
    storageKey: PREF_KEYS.catalogActiveTab,
    defaultTab: 'active-providers',
    allowed: ALLOWED,
    urlParamsToReset: ['provider_id', 'model_kind', 'model_class', 'hosting', 'availability', 'sort', 'sort_dir']
  });
}
