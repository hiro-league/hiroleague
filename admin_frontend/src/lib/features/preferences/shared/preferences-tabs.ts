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

/** Intro paragraph shown above a tab's cards — a live section description or a static string. */
export type PrefTabIntro = { sectionKey: string } | { text: string };

/**
 * One page-level preference tab. This registry is the SINGLE source for a tab's identity: its strip
 * label, its manifest (or hand-rolled marker), the intro paragraph, and any legacy `#hash` aliases.
 * Every per-tab map below (`PREFERENCE_TABS`, the html/panel ids, the manifest + legacy maps) is
 * DERIVED from it — adding a tab means adding one entry here, not editing six parallel objects. The
 * `preferences-tab-map` test asserts `PREFERENCE_TAB_PATH_RULES` still routes every path to one tab.
 */
export type PrefTabDescriptor = {
  id: PreferenceTabId;
  label: string;
  /** Manifest-driven tabs render via `PrefManifestTab`; hand-rolled tabs (Model Profiles) omit it. */
  manifest?: PrefTabManifest;
  /** Optional intro paragraph above the cards. */
  intro?: PrefTabIntro;
  /** Interactive header affordance rendered beside the intro (string key → widget in PrefManifestTab). */
  headerAction?: 'knowledgeBrowse';
  /** Extra legacy `#hash` aliases beyond the canonical `preferences-<id>` (from merged/removed tabs). */
  legacyAliases?: readonly string[];
  /** Field paths + section titles a hand-rolled (non-manifest) tab contributes, in render order. */
  handRolled?: { fields: readonly string[]; sections: readonly string[] };
};

// Registry order drives the tab strip order AND the page's field/section render order.
export const PREFERENCE_TAB_REGISTRY: readonly PrefTabDescriptor[] = [
  {
    id: 'models',
    label: 'General',
    manifest: MODELS_MANIFEST,
    intro: { sectionKey: 'llm' },
    // Media settings were merged into the General tab; keep the legacy anchor working.
    legacyAliases: ['preferences-media']
  },
  {
    id: 'agent',
    label: 'Agent',
    manifest: AGENT_MANIFEST,
    intro: { sectionKey: 'chat' },
    // Agent Memory tab was merged into the Agent tab; keep the legacy anchor working.
    legacyAliases: ['preferences-memory']
  },
  {
    id: 'graph-engine',
    label: 'Memory',
    manifest: GRAPH_ENGINE_MANIFEST,
    intro: {
      text:
        'One Graphiti temporal-graph engine, shared by Agent Memory and Knowledge — these models ' +
        'and graph-search settings apply to both. (Whether Knowledge retrieval uses the graph is the ' +
        '"Graph backend" toggle on the Knowledge tab.) Changing the graph embedder re-indexes all ' +
        'graph data.'
    }
  },
  {
    id: 'knowledge',
    label: 'Knowledge',
    manifest: KNOWLEDGE_MANIFEST,
    intro: { sectionKey: 'knowledge' },
    headerAction: 'knowledgeBrowse'
  },
  {
    id: 'eval',
    label: 'Eval',
    manifest: EVAL_MANIFEST,
    intro: {
      text:
        'Settings for the evaluation harness — the answer and judge models the eval runs use, and ' +
        "the memory-eval answer/judge prompt libraries. Eval-only; these don't affect production " +
        'chat, knowledge, or memory.'
    }
  },
  {
    id: 'tuning-profiles',
    label: 'Model Profiles',
    // Hand-rolled table CRUD (no manifest) — registers its single field + section name explicitly.
    handRolled: { fields: ['tuning_profiles'], sections: ['Model Profiles'] }
  }
];

// The html/panel ids follow a fixed convention (`preferences-tab-<id>` / `preferences-panel-<id>`),
// so they're derived — no hand-maintained id maps to drift from the registry.
export const PREFERENCE_TAB_IDS = Object.fromEntries(
  PREFERENCE_TAB_REGISTRY.map((tab) => [tab.id, `preferences-tab-${tab.id}`])
) as Record<PreferenceTabId, string>;

export const PREFERENCE_TAB_PANEL_IDS = Object.fromEntries(
  PREFERENCE_TAB_REGISTRY.map((tab) => [tab.id, `preferences-panel-${tab.id}`])
) as Record<PreferenceTabId, string>;

export const PREFERENCE_TABS: { id: PreferenceTabId; label: string }[] = PREFERENCE_TAB_REGISTRY.map(
  (tab) => ({ id: tab.id, label: tab.label })
);

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
  // The chat retrieval-agent config is memory-engine-specific (not general chat), so it renders on
  // the shared Memory (graph-engine) tab, not the Agent tab — a longer-prefix override of `memory`.
  { prefix: 'memory.retrieval', tab: 'graph-engine' },
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
  // The retrieval-agent section (model/profile, prompt library, loop caps) and the answerer/judge
  // render caps are eval-only — moved to the Eval tab (were on the shared graph-engine tab).
  { prefix: 'graph.eval.retrieval_model', tab: 'eval' },
  { prefix: 'graph.eval.retrieval_tuning_profile', tab: 'eval' },
  { prefix: 'graph.eval.retrieval_agent', tab: 'eval' },
  { prefix: 'graph.eval.retrieval_agent_prompts', tab: 'eval' },
  { prefix: 'graph.eval.active_retrieval_agent_prompt_id', tab: 'eval' },
  { prefix: 'graph.eval.max_elements_per_kind', tab: 'eval' },
  { prefix: 'graph.eval.max_fact_chars', tab: 'eval' },
  { prefix: 'graph.eval.max_episode_chars', tab: 'eval' },
  { prefix: 'graph.eval.max_summary_chars', tab: 'eval' },
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
function tabFieldPaths(tab: PrefTabDescriptor): readonly string[] {
  return tab.manifest ? manifestFieldPaths(tab.manifest) : (tab.handRolled?.fields ?? []);
}

function tabSectionTitles(tab: PrefTabDescriptor): readonly string[] {
  return tab.manifest ? manifestCardSections(tab.manifest) : (tab.handRolled?.sections ?? []);
}

// Field render order across the page: tab order, then each tab's manifest field order. Orders search
// arrow-nav to follow the visual top-to-bottom layout. DERIVED — the manifests are the single source.
export const PREFERENCE_FIELD_ORDER: readonly string[] = PREFERENCE_TAB_REGISTRY.flatMap(tabFieldPaths);

// Card/section titles in render order (tab order, then card order within each tab). Drives
// search-result section grouping/ordering. DERIVED from the manifests' card order.
export const PREFERENCE_SECTION_ORDER: readonly string[] =
  PREFERENCE_TAB_REGISTRY.flatMap(tabSectionTitles);

// path → section (card) title, merged across every manifest (+ each hand-rolled tab's section).
// Each path lives in exactly one tab, so the merge can't collide.
const PREFERENCE_SECTION_BY_PATH: Record<string, string> = {};
for (const tab of PREFERENCE_TAB_REGISTRY) {
  if (tab.manifest) {
    Object.assign(PREFERENCE_SECTION_BY_PATH, manifestSections(tab.manifest));
  } else if (tab.handRolled) {
    for (const path of tab.handRolled.fields) PREFERENCE_SECTION_BY_PATH[path] = tab.handRolled.sections[0];
  }
}

/**
 * Resolve a dotted preference path to its card/section title. Returns `null` for a path no manifest
 * surfaces (e.g. an editable field the UI intentionally doesn't render) — the search index treats a
 * null section as "not navigable" and omits it.
 */
export function sectionForPreferencePath(path: string): string | null {
  return PREFERENCE_SECTION_BY_PATH[path] ?? null;
}

// Legacy `#preferences-*` scroll anchors from the pre-tab layout. DERIVED — each tab's canonical
// `preferences-<id>` anchor plus any `legacyAliases` from merged/removed tabs.
export const LEGACY_PREFERENCE_HASH_TO_TAB: Record<string, PreferenceTabId> = Object.fromEntries(
  PREFERENCE_TAB_REGISTRY.flatMap((tab) => [
    [`preferences-${tab.id}`, tab.id] as const,
    ...(tab.legacyAliases ?? []).map((hash) => [hash, tab.id] as const)
  ])
);

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
