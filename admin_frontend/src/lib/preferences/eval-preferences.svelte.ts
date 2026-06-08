import { PREF_KEYS, type EvalTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly EvalTabPreference[] = ['memory', 'knowledge'] as const;

export type EvalTabPreferences = TabPreferences<EvalTabPreference>;

export function createEvalPreferences(): EvalTabPreferences {
  return createTabPreferences<EvalTabPreference>({
    storageKey: PREF_KEYS.evalActiveTab,
    defaultTab: 'memory',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}
