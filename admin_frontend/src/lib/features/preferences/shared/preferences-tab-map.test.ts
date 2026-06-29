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
    expect(tabForPreferencePath('llm.default_chat')).toBe('models');
    expect(tabForPreferencePath('media.input.voice')).toBe('models');
    expect(tabForPreferencePath('memory.search.top_k')).toBe('agent');
    expect(tabForPreferencePath('chat.instructions')).toBe('agent');
    expect(tabForPreferencePath('knowledge.retrieval.top_k')).toBe('knowledge');
    // `graph.backend` is a longer-prefix override that beats the broad `graph` rule.
    expect(tabForPreferencePath('graph.backend')).toBe('knowledge');
    // `graph.eval.*` split: answer/judge → Eval; the retrieval loop + render knobs → graph engine.
    expect(tabForPreferencePath('graph.eval.answer_model')).toBe('eval');
    expect(tabForPreferencePath('graph.eval.judge_prompt')).toBe('eval');
    expect(tabForPreferencePath('graph.eval.retrieval_model')).toBe('graph-engine');
    expect(tabForPreferencePath('graph.eval.show_event_time')).toBe('graph-engine');
    expect(tabForPreferencePath('graph.reranker.model_id')).toBe('graph-engine');
    expect(tabForPreferencePath('tuning_profiles')).toBe('tuning-profiles');
  });

  it('returns null for paths not surfaced on the Settings page', () => {
    expect(tabForPreferencePath('image_profiles')).toBeNull();
    expect(tabForPreferencePath('totally.unknown.path')).toBeNull();
  });
});
