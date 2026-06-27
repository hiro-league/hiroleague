/** Page-level preference tabs (`?tab=` on `/preferences`). */
export type PreferenceTabId =
  | 'models'
  | 'knowledge'
  | 'graph-engine'
  | 'eval'
  | 'agent'
  | 'tuning-profiles';

export const DEFAULT_PREFERENCE_TAB: PreferenceTabId = 'models';

export const PREFERENCE_TABLIST_LABEL = 'Preference sections';

export const PREFERENCE_TAB_IDS: Record<PreferenceTabId, string> = {
  models: 'preferences-tab-models',
  knowledge: 'preferences-tab-knowledge',
  'graph-engine': 'preferences-tab-graph-engine',
  eval: 'preferences-tab-eval',
  agent: 'preferences-tab-agent',
  'tuning-profiles': 'preferences-tab-tuning-profiles'
};

export const PREFERENCE_TAB_PANEL_IDS: Record<PreferenceTabId, string> = {
  models: 'preferences-panel-models',
  knowledge: 'preferences-panel-knowledge',
  'graph-engine': 'preferences-panel-graph-engine',
  eval: 'preferences-panel-eval',
  agent: 'preferences-panel-agent',
  'tuning-profiles': 'preferences-panel-tuning-profiles'
};

export const PREFERENCE_TABS: { id: PreferenceTabId; label: string }[] = [
  { id: 'models', label: 'General' },
  { id: 'agent', label: 'Agent' },
  { id: 'graph-engine', label: 'Graph Engine' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'eval', label: 'Eval' },
  { id: 'tuning-profiles', label: 'Model Profiles' }
];

/** Legacy `#preferences-*` scroll anchors from the pre-tab layout. */
export const LEGACY_PREFERENCE_HASH_TO_TAB: Record<string, PreferenceTabId> = {
  'preferences-models': 'models',
  // Media settings were merged into the General (models) tab; keep the legacy anchor working.
  'preferences-media': 'models',
  // Agent Memory tab was merged into the Agent tab; keep the legacy anchor working.
  'preferences-memory': 'agent',
  'preferences-knowledge': 'knowledge',
  'preferences-graph-engine': 'graph-engine',
  'preferences-eval': 'eval',
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

/** Migrate legacy `#preferences-*` scroll anchors to `?tab=` before tab prefs initialize. */
export function migrateLegacyPreferenceHash(): void {
  if (typeof window === 'undefined') return;
  const hash = window.location.hash.slice(1);
  if (!hash) return;
  const tab = LEGACY_PREFERENCE_HASH_TO_TAB[hash];
  if (!tab) return;
  const nextUrl = new URL(window.location.href);
  nextUrl.hash = '';
  if (tab !== DEFAULT_PREFERENCE_TAB) {
    nextUrl.searchParams.set('tab', tab);
  } else {
    nextUrl.searchParams.delete('tab');
  }
  window.history.replaceState(null, '', `${nextUrl.pathname}${nextUrl.search}`);
}
