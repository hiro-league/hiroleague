import { PREF_KEYS, type EvalSubtabPreference, type EvalTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly EvalTabPreference[] = ['memory', 'knowledge'] as const;
const ALLOWED_SUBTABS: readonly EvalSubtabPreference[] = [
  'execute',
  'corpus',
  'answers',
  'report'
] as const;

export type EvalTabPreferences = TabPreferences<EvalTabPreference>;
export type EvalSubtabPreferences = TabPreferences<EvalSubtabPreference>;

/** Page-level track tab (`?tab=memory|knowledge`). */
export function createEvalPreferences(): EvalTabPreferences {
  return createTabPreferences<EvalTabPreference>({
    storageKey: PREF_KEYS.evalActiveTab,
    defaultTab: 'memory',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}

/** Second-level section sub-tab (`?sub=execute|corpus|answers|report`) — coexists with `?tab=`.
 *  Always serialises the id (no omit-default) so a deep link / refresh reopens the same sub-tab. */
export function createEvalSubtabPreferences(): EvalSubtabPreferences {
  return createTabPreferences<EvalSubtabPreference>({
    storageKey: PREF_KEYS.evalSubtab,
    defaultTab: 'execute',
    allowed: ALLOWED_SUBTABS,
    param: 'sub'
  });
}
