import { GRAPH_ENGINE_MANIFEST } from '$lib/features/preferences/sections/graph-engine/graph-engine-manifest';
import { EVAL_MANIFEST } from '$lib/features/preferences/sections/eval/eval-manifest';
import { AGENT_MANIFEST } from '$lib/features/preferences/sections/agent-manifest';
import { KNOWLEDGE_MANIFEST } from '$lib/features/preferences/sections/knowledge/knowledge-manifest';
import { MODELS_MANIFEST } from '$lib/features/preferences/sections/models-manifest';
import {
  manifestCardSections,
  manifestFieldPaths,
  manifestSections,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';

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
  { prefix: 'graph.eval.active_answer_prompt_id', tab: 'eval' },
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

// ---------------------------------------------------------------------------
// Manifest-derived field order + section map (single source: the per-tab manifests)
// ---------------------------------------------------------------------------
//
// Each manifest-driven tab owns its field ORDER, card/section titles, and path→section map. We
// derive all of that straight from the manifests, so there is nothing to keep in sync with the
// section components: adding/reordering a field or renaming a card in a manifest updates the search
// index automatically. The hand-rolled `tuning-profiles` tab has no manifest, so it registers its
// single field + section name explicitly. (`tabForPreferencePath` above stays a small prefix table —
// the subtree-ownership map that lets the per-manifest tests catch a field someone forgot to add to
// a manifest.)
const PREFERENCE_TAB_MANIFESTS: Partial<Record<PreferenceTabId, PrefTabManifest>> = {
  models: MODELS_MANIFEST,
  agent: AGENT_MANIFEST,
  'graph-engine': GRAPH_ENGINE_MANIFEST,
  knowledge: KNOWLEDGE_MANIFEST,
  eval: EVAL_MANIFEST
};

// Field paths + section titles a hand-rolled (non-manifest) tab contributes, in render order.
const HANDROLLED_TAB_FIELDS: Partial<Record<PreferenceTabId, readonly string[]>> = {
  'tuning-profiles': ['tuning_profiles']
};
const HANDROLLED_TAB_SECTIONS: Partial<Record<PreferenceTabId, readonly string[]>> = {
  'tuning-profiles': ['Model Profiles']
};

function tabFieldPaths(tab: PreferenceTabId): readonly string[] {
  const manifest = PREFERENCE_TAB_MANIFESTS[tab];
  return manifest ? manifestFieldPaths(manifest) : (HANDROLLED_TAB_FIELDS[tab] ?? []);
}

function tabSectionTitles(tab: PreferenceTabId): readonly string[] {
  const manifest = PREFERENCE_TAB_MANIFESTS[tab];
  return manifest ? manifestCardSections(manifest) : (HANDROLLED_TAB_SECTIONS[tab] ?? []);
}

// Field render order across the page: tab order, then each tab's manifest field order. Orders search
// arrow-nav to follow the visual top-to-bottom layout. DERIVED — the manifests are the single source.
export const PREFERENCE_FIELD_ORDER: readonly string[] = PREFERENCE_TABS.flatMap((tab) =>
  tabFieldPaths(tab.id)
);

// Card/section titles in render order (tab order, then card order within each tab). Drives
// search-result section grouping/ordering. DERIVED from the manifests' card order.
export const PREFERENCE_SECTION_ORDER: readonly string[] = PREFERENCE_TABS.flatMap((tab) =>
  tabSectionTitles(tab.id)
);

// path → section (card) title, merged across every manifest (+ the hand-rolled Model Profiles tab).
// Each path lives in exactly one tab, so the merge can't collide.
const PREFERENCE_SECTION_BY_PATH: Record<string, string> = { tuning_profiles: 'Model Profiles' };
for (const manifest of Object.values(PREFERENCE_TAB_MANIFESTS)) {
  if (manifest) Object.assign(PREFERENCE_SECTION_BY_PATH, manifestSections(manifest));
}

/**
 * Resolve a dotted preference path to its card/section title. Returns `null` for a path no manifest
 * surfaces (e.g. an editable field the UI intentionally doesn't render) — the search index treats a
 * null section as "not navigable" and omits it.
 */
export function sectionForPreferencePath(path: string): string | null {
  return PREFERENCE_SECTION_BY_PATH[path] ?? null;
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
