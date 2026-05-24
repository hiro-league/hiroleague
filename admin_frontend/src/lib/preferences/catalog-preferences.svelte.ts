import { PREF_KEYS, type CatalogTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly CatalogTabPreference[] = ['providers', 'models'] as const;

export function createCatalogPreferences(): TabPreferences<CatalogTabPreference> {
  return createTabPreferences<CatalogTabPreference>({
    storageKey: PREF_KEYS.catalogActiveTab,
    defaultTab: 'providers',
    allowed: ALLOWED,
    urlParamsToReset: ['provider_id', 'model_kind', 'model_class', 'hosting', 'sort', 'sort_dir']
  });
}
