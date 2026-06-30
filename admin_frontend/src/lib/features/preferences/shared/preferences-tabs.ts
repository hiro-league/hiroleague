import { GRAPH_ENGINE_FIELD_ORDER } from '$lib/features/preferences/sections/graph-engine/graph-engine-manifest';
import { EVAL_FIELD_ORDER } from '$lib/features/preferences/sections/eval/eval-manifest';
import { AGENT_FIELD_ORDER } from '$lib/features/preferences/sections/agent-manifest';
import { KNOWLEDGE_FIELD_ORDER } from '$lib/features/preferences/sections/knowledge/knowledge-manifest';
import { MODELS_FIELD_ORDER } from '$lib/features/preferences/sections/models-manifest';

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

// Path → section (card) title, for the search autocomplete's "Tab › Section" locator line. Same
// longest-prefix-wins scheme as the tab map. These MUST mirror the `<PrefSectionCard title=…>` (and
// a couple of `<PrefPanel>`) labels in the section components; if a card is renamed or a field moves
// cards, update the matching rule here. Missing coverage degrades gracefully (the autocomplete just
// omits the section), so this is best-effort polish, not correctness-critical.
const PREFERENCE_SECTION_PATH_RULES: { prefix: string; section: string }[] = [
  // General
  { prefix: 'llm', section: 'Default models' },
  { prefix: 'media', section: 'Modalities' },
  // Agent
  { prefix: 'memory.user_name', section: 'Chat Settings' },
  { prefix: 'chat', section: 'Chat Settings' },
  { prefix: 'memory', section: 'Agent memory' },
  // Knowledge
  { prefix: 'knowledge.retrieval', section: 'Retrieval defaults' },
  { prefix: 'knowledge.answering', section: 'Knowledge Answering (Ask Tab)' },
  { prefix: 'knowledge.rewrite', section: 'Knowledge Answering (Ask Tab)' },
  { prefix: 'knowledge.default_tuning_profile', section: 'Knowledge Answering (Ask Tab)' },
  { prefix: 'knowledge', section: 'Indexing Options' },
  { prefix: 'graph.backend', section: 'Indexing Options' },
  // Eval
  { prefix: 'graph.eval.answer_model', section: 'Evaluation Models' },
  { prefix: 'graph.eval.answer_tuning_profile', section: 'Evaluation Models' },
  { prefix: 'graph.eval.judge_model', section: 'Evaluation Models' },
  { prefix: 'graph.eval.judge_tuning_profile', section: 'Evaluation Models' },
  { prefix: 'graph.eval.answer_prompts', section: 'Prompts' },
  { prefix: 'graph.eval.active_answer_prompt_id', section: 'Prompts' },
  { prefix: 'graph.eval.judge_prompt', section: 'Prompts' },
  // Memory (shared graph engine)
  { prefix: 'graph.eval.retrieval_model', section: 'Retrieval Agent Model & Prompt' },
  { prefix: 'graph.eval.retrieval_tuning_profile', section: 'Retrieval Agent Model & Prompt' },
  { prefix: 'graph.eval.active_retrieval_agent_prompt_id', section: 'Retrieval Agent Model & Prompt' },
  { prefix: 'graph.eval.retrieval_agent_prompts', section: 'Retrieval Agent Model & Prompt' },
  { prefix: 'graph.eval.retrieval_agent', section: 'Retrieval Agent' },
  { prefix: 'graph.eval.max_elements_per_kind', section: 'Retrieval Agent' },
  { prefix: 'graph.eval.max_fact_chars', section: 'Retrieval Agent' },
  { prefix: 'graph.eval.max_episode_chars', section: 'Retrieval Agent' },
  { prefix: 'graph.eval.max_summary_chars', section: 'Retrieval Agent' },
  { prefix: 'graph.eval.show_event_time', section: 'Graph search & indexing' },
  { prefix: 'graph.eval.show_expired_at', section: 'Graph search & indexing' },
  { prefix: 'graph.eval.show_superseded', section: 'Graph search & indexing' },
  { prefix: 'graph.reranker', section: 'Graphiti Reranker (Cross-encoder)' },
  { prefix: 'graph.view', section: 'Graph view (display)' },
  { prefix: 'graph.extraction_model', section: 'Graph Extraction' },
  { prefix: 'graph.extraction_tuning_profile', section: 'Graph Extraction' },
  { prefix: 'graph.small_model', section: 'Graph Extraction' },
  { prefix: 'graph.small_tuning_profile', section: 'Graph Extraction' },
  { prefix: 'graph.embedder_model', section: 'Graph Extraction' },
  { prefix: 'graph.entity_ontology', section: 'Graph Extraction' },
  { prefix: 'graph.custom_extraction_instructions', section: 'Graph Extraction' },
  { prefix: 'graph', section: 'Graph search & indexing' },
  // Model Profiles
  { prefix: 'tuning_profiles', section: 'Model Profiles' }
];

// Sections in the order they render on the page (tab order, then card order within each tab). Drives
// search-result ordering so arrowing follows the visual top-to-bottom layout instead of the schema's
// model-definition order. Keep in sync with the section components' card order.
export const PREFERENCE_SECTION_ORDER: readonly string[] = [
  // General
  'Default models',
  'Modalities',
  // Agent
  'Chat Settings',
  'Agent memory',
  // Memory (shared graph engine)
  'Graph Extraction',
  'Graph search & indexing',
  'Graphiti Reranker (Cross-encoder)',
  'Retrieval Agent Model & Prompt',
  'Retrieval Agent',
  'Graph view (display)',
  // Knowledge
  'Indexing Options',
  'Retrieval defaults',
  'Knowledge Answering (Ask Tab)',
  // Eval
  'Evaluation Models',
  'Prompts',
  // Model Profiles
  'Model Profiles'
];

// Field render order WITHIN each section, mirroring the markup order of the section components (the
// 2-col grids fill left-to-right, top-to-bottom, so source order = visual order). Used to order
// search results within a card so arrowing follows the page exactly, instead of the schema's
// model-definition order. Paths not listed here fall back to schema order after the listed ones in
// their section. Keep in sync with the cards; the `preferences-search-index` test guards that every
// entry is a real, unique schema path.
export const PREFERENCE_FIELD_ORDER: readonly string[] = [
  // General (models) — DERIVED from MODELS_MANIFEST (see models-manifest.ts).
  ...MODELS_FIELD_ORDER,
  // Agent — DERIVED from AGENT_MANIFEST (see agent-manifest.ts).
  ...AGENT_FIELD_ORDER,
  // Memory (shared graph engine) — DERIVED from GRAPH_ENGINE_MANIFEST so render order and search
  // order share one source and can't drift. Add/reorder Memory-tab fields in graph-engine-manifest.ts.
  ...GRAPH_ENGINE_FIELD_ORDER,
  // Knowledge — DERIVED from KNOWLEDGE_MANIFEST (see knowledge-manifest.ts).
  ...KNOWLEDGE_FIELD_ORDER,
  // Eval — DERIVED from EVAL_MANIFEST (single source for render + search order; see eval-manifest.ts).
  ...EVAL_FIELD_ORDER,
  // Model Profiles
  'tuning_profiles'
];

/** Resolve a dotted preference path to its card/section title (longest matching prefix wins). */
export function sectionForPreferencePath(path: string): string | null {
  let best: { prefix: string; section: string } | null = null;
  for (const rule of PREFERENCE_SECTION_PATH_RULES) {
    if (prefixMatchesPath(path, rule.prefix) && (!best || rule.prefix.length > best.prefix.length)) {
      best = rule;
    }
  }
  return best?.section ?? null;
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
