/**
 * Tuning-profile CRUD over the draft — split out of the preferences controller (Tier-2.2). Pure draft
 * mutations (no API): create / duplicate / delete / update / reset-locked + the default-profile
 * pickers, each marking the page dirty. The controller composes this and re-exposes it; the immediate
 * single-profile PATCH (`saveProfileNow`) stays on the controller since it needs baseline + the save
 * pipeline.
 */
import type { TuningProfile, WorkspacePreferences } from '$lib/api/preferences';
import type { ThinkingValue } from '$lib/features/preferences/shared/preferences-constants';

type Options = {
  /** Live draft accessor (the controller's `$state` draft). */
  draft: () => WorkspacePreferences | null;
  markDirty: () => void;
};

export function createTuningProfiles({ draft: getDraft, markDirty }: Options) {
  const profileEntries = $derived.by<[string, TuningProfile][]>(() =>
    Object.entries(getDraft()?.tuning_profiles ?? {}).sort(([, a], [, b]) =>
      a.label.localeCompare(b.label)
    )
  );

  function setDefaultTuningProfile(scope: 'llm' | 'memory' | 'knowledge', id: string) {
    const draft = getDraft();
    if (!draft || !draft.tuning_profiles[id]) return;
    if (scope === 'llm') draft.llm.default_tuning_profile = id;
    else if (scope === 'memory') draft.memory.default_tuning_profile = id;
    else draft.knowledge.default_tuning_profile = id;
    markDirty();
  }

  function updateProfile(
    id: string,
    field: 'label' | 'temperature' | 'max_tokens' | 'thinking' | 'num_ctx',
    value: string
  ) {
    const draft = getDraft();
    if (!draft || !draft.tuning_profiles[id]) return;
    const profile = draft.tuning_profiles[id];
    if (field === 'label') profile.label = value;
    if (field === 'temperature') profile.temperature = Number(value);
    if (field === 'max_tokens') profile.max_tokens = Number(value);
    if (field === 'thinking') profile.thinking = value === 'default' ? null : (value as ThinkingValue);
    // Blank = unset (null) → provider default; otherwise the Ollama num_ctx override.
    if (field === 'num_ctx') profile.num_ctx = value.trim() === '' ? null : Number(value);
    markDirty();
  }

  function createProfile() {
    const draft = getDraft();
    if (!draft) return;
    let index = Object.keys(draft.tuning_profiles).length + 1;
    let id = `custom_${index}`;
    while (draft.tuning_profiles[id]) {
      index += 1;
      id = `custom_${index}`;
    }
    draft.tuning_profiles[id] = {
      label: `Custom ${index}`,
      locked: false,
      temperature: 0.7,
      max_tokens: 2048,
      thinking: null,
      num_ctx: null
    };
    markDirty();
  }

  // Duplicate any profile (built-in or custom) into a new editable custom profile. The table view
  // makes "clone the closest preset, then tweak" the happy path for creating a profile.
  function duplicateProfile(id: string) {
    const draft = getDraft();
    if (!draft) return;
    const source = draft.tuning_profiles[id];
    if (!source) return;
    let index = Object.keys(draft.tuning_profiles).length + 1;
    let newId = `custom_${index}`;
    while (draft.tuning_profiles[newId]) {
      index += 1;
      newId = `custom_${index}`;
    }
    draft.tuning_profiles[newId] = {
      label: `${source.label.trim() || id} (copy)`,
      locked: false,
      temperature: source.temperature,
      max_tokens: source.max_tokens,
      thinking: source.thinking,
      num_ctx: source.num_ctx
    };
    markDirty();
  }

  function deleteProfile(id: string) {
    const draft = getDraft();
    if (!draft) return;
    const profile = draft.tuning_profiles[id];
    if (!profile || profile.locked) return;
    delete draft.tuning_profiles[id];
    if (draft.llm.default_tuning_profile === id) draft.llm.default_tuning_profile = 'balanced_chat';
    if (draft.memory.default_tuning_profile === id) {
      draft.memory.default_tuning_profile = 'memory_extraction';
    }
    if (draft.knowledge.default_tuning_profile === id) {
      draft.knowledge.default_tuning_profile = 'knowledge_answering';
    }
    markDirty();
  }

  function resetLockedProfile(id: string) {
    const draft = getDraft();
    if (!draft) return;
    if (id === 'balanced_chat') {
      draft.tuning_profiles[id] = {
        label: 'Balanced chat',
        locked: true,
        temperature: 0.7,
        max_tokens: 2048,
        thinking: null,
        num_ctx: null
      };
    } else if (id === 'memory_extraction') {
      draft.tuning_profiles[id] = {
        label: 'Memory extraction',
        locked: true,
        temperature: 0,
        max_tokens: 8192,
        thinking: 'low',
        num_ctx: null
      };
    } else if (id === 'knowledge_answering') {
      draft.tuning_profiles[id] = {
        label: 'Knowledge answering',
        locked: true,
        temperature: 0.2,
        max_tokens: 1600,
        thinking: null,
        num_ctx: null
      };
    }
    markDirty();
  }

  return {
    get profileEntries() {
      return profileEntries;
    },
    setDefaultTuningProfile,
    updateProfile,
    createProfile,
    duplicateProfile,
    deleteProfile,
    resetLockedProfile
  };
}
