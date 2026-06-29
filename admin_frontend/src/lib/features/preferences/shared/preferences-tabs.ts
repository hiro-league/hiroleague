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
  { id: 'graph-engine', label: 'Memory' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'eval', label: 'Eval' },
  { id: 'tuning-profiles', label: 'Model Profiles' }
];

// ---------------------------------------------------------------------------
// Path → tab assignment (Settings search / index)
// ---------------------------------------------------------------------------
//
// A field's TAB is a UI grouping, not a backend concept, so it lives here as data rather than in
// the schema. `tabForPreferencePath` resolves a dotted preference path to its tab by LONGEST
// matching prefix — so adding a field under an existing subtree (e.g. another `graph.*` knob) needs
// no change here; only a brand-new top-level subtree, or a field that belongs in a different tab
// than its subtree (like `graph.backend`, which renders on the Knowledge tab), needs an entry.
//
// The `preferences-tab-map` test asserts every editable schema path resolves to exactly one tab, so
// a newly added setting that no rule covers fails CI rather than silently dropping out of search.
const PREFERENCE_TAB_PATH_RULES: { prefix: string; tab: PreferenceTabId }[] = [
  { prefix: 'llm', tab: 'models' },
  { prefix: 'media', tab: 'models' },
  { prefix: 'memory', tab: 'agent' },
  { prefix: 'chat', tab: 'agent' },
  { prefix: 'knowledge', tab: 'knowledge' },
  // Graph master switch is surfaced on the Knowledge tab, not the shared graph-engine tab.
  { prefix: 'graph.backend', tab: 'knowledge' },
  // `graph.eval.*` is split: the answer + judge models/prompts live on the Eval tab; everything
  // else under it (the agentic retrieval loop, render caps, temporal flags) renders under the
  // shared graph engine on the Memory tab — caught by the broader `graph` rule below.
  { prefix: 'graph.eval.answer_model', tab: 'eval' },
  { prefix: 'graph.eval.answer_tuning_profile', tab: 'eval' },
  { prefix: 'graph.eval.answer_prompts', tab: 'eval' },
  { prefix: 'graph.eval.judge_model', tab: 'eval' },
  { prefix: 'graph.eval.judge_tuning_profile', tab: 'eval' },
  { prefix: 'graph.eval.judge_prompt', tab: 'eval' },
  { prefix: 'graph', tab: 'graph-engine' },
  { prefix: 'tuning_profiles', tab: 'tuning-profiles' }
];

// A rule matches a path when the path IS the prefix or sits under it on a dotted-segment boundary
// (so `graph` matches `graph.k_hop` but never a hypothetical `graphextra`).
function prefixMatchesPath(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}.`);
}

/**
 * Resolve a dotted preference path to the Settings tab that renders it (longest matching prefix
 * wins). Returns `null` for paths not surfaced on the Settings page (e.g. image-lab-only fields),
 * so callers building counts/navigation can skip them.
 */
export function tabForPreferencePath(path: string): PreferenceTabId | null {
  let best: { prefix: string; tab: PreferenceTabId } | null = null;
  for (const rule of PREFERENCE_TAB_PATH_RULES) {
    if (prefixMatchesPath(path, rule.prefix) && (!best || rule.prefix.length > best.prefix.length)) {
      best = rule;
    }
  }
  return best?.tab ?? null;
}

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
