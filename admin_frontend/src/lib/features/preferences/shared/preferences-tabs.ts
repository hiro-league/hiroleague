/** Page-level preference tabs (`?tab=` on `/preferences`). */
export type PreferenceTabId =
  | 'models'
  | 'media'
  | 'memory'
  | 'knowledge'
  | 'agent'
  | 'tuning-profiles';

export const DEFAULT_PREFERENCE_TAB: PreferenceTabId = 'models';

export const PREFERENCE_TABLIST_LABEL = 'Preference sections';

export const PREFERENCE_TAB_IDS: Record<PreferenceTabId, string> = {
  models: 'preferences-tab-models',
  media: 'preferences-tab-media',
  memory: 'preferences-tab-memory',
  knowledge: 'preferences-tab-knowledge',
  agent: 'preferences-tab-agent',
  'tuning-profiles': 'preferences-tab-tuning-profiles'
};

export const PREFERENCE_TAB_PANEL_IDS: Record<PreferenceTabId, string> = {
  models: 'preferences-panel-models',
  media: 'preferences-panel-media',
  memory: 'preferences-panel-memory',
  knowledge: 'preferences-panel-knowledge',
  agent: 'preferences-panel-agent',
  'tuning-profiles': 'preferences-panel-tuning-profiles'
};

export const PREFERENCE_TABS: { id: PreferenceTabId; label: string }[] = [
  { id: 'models', label: 'Models' },
  { id: 'agent', label: 'Agent' },
  { id: 'memory', label: 'Agent Memory' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'tuning-profiles', label: 'Model Profiles' },
  { id: 'media', label: 'Media' }
];

/** Legacy `#preferences-*` scroll anchors from the pre-tab layout. */
export const LEGACY_PREFERENCE_HASH_TO_TAB: Record<string, PreferenceTabId> = {
  'preferences-models': 'models',
  'preferences-media': 'media',
  'preferences-memory': 'memory',
  'preferences-knowledge': 'knowledge',
  'preferences-agent': 'agent',
  'preferences-tuning-profiles': 'tuning-profiles'
};

export function preferenceTabQuery(tab: PreferenceTabId): string {
  if (tab === DEFAULT_PREFERENCE_TAB) return '';
  return `?tab=${tab}`;
}

export function preferenceTabHref(tab: PreferenceTabId, basePath = ''): string {
  return `${basePath}/preferences${preferenceTabQuery(tab)}`;
}
