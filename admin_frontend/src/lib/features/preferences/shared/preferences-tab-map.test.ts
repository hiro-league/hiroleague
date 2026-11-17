import { describe, expect, it } from 'vitest';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import { tabForPreferencePath } from './preferences-tabs';

// Drift guard for the Settings tab map: every EDITABLE preference path must resolve to exactly one
// tab, so a newly added setting that no rule in `PREFERENCE_TAB_PATH_RULES` covers fails CI rather
// than silently dropping out of the Settings search/index. "Editable" excludes read-only
// enrichment fields and image-lab-only fields (flagged `preferencesSaveSkip`), which the Settings
// tabs intentionally don't surface.
const editablePaths = Object.values(PREFERENCES_FIELD_SCHEMA)
  .filter((meta) => !meta.readOnly && !meta.preferencesSaveSkip)
  .map((meta) => meta.path);

describe('tabForPreferencePath (preferences tab map)', () => {
  it('assigns every editable preference path to a tab', () => {
    const unassigned = editablePaths.filter((path) => tabForPreferencePath(path) === null);
    expect(unassigned).toEqual([]);
  });

  it('routes subtree, override, and split paths to the right tab', () => {
    expect(tabForPreferencePath('llm.chat_profile')).toBe('models');
    // Phase 7b step 5: Hiro's voice renders on General; the other `voice.*` paths are the Catalog's.
    expect(tabForPreferencePath('voice.hiro_profile')).toBe('models');
    expect(tabForPreferencePath('voice.profiles')).toBeNull();
    expect(tabForPreferencePath('media.input.voice')).toBe('models');
    expect(tabForPreferencePath('memory.search.enabled')).toBe('agent');
    // `memory.retrieval.*` is a longer-prefix override → the shared Memory (graph-engine) tab.
    expect(tabForPreferencePath('memory.retrieval.active_prompt_id')).toBe('graph-engine');
    expect(tabForPreferencePath('memory.retrieval.limits.max_agent_turns')).toBe('graph-engine');
    expect(tabForPreferencePath('memory.retrieval.profile')).toBe('graph-engine');
    expect(tabForPreferencePath('memory.retrieval.prompts')).toBe('graph-engine');
    expect(tabForPreferencePath('chat.instructions')).toBe('agent');
    expect(tabForPreferencePath('knowledge.retrieval.top_k')).toBe('knowledge');
    // `graph.backend` is a longer-prefix override that beats the broad `graph` rule.
    expect(tabForPreferencePath('graph.backend')).toBe('knowledge');
    expect(tabForPreferencePath('graph.extraction_profile')).toBe('graph-engine');
    expect(tabForPreferencePath('knowledge.answering.rewrite_profile')).toBe('knowledge');
    expect(tabForPreferencePath('graph.reranker.model_id')).toBe('graph-engine');
  });

  it('returns null for paths not surfaced on the Settings page', () => {
    expect(tabForPreferencePath('image_profiles')).toBeNull();
    expect(tabForPreferencePath('totally.unknown.path')).toBeNull();
  });
});
