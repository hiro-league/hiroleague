import { PREF_KEYS, type KnowledgeTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly KnowledgeTabPreference[] = ['browse', 'ingest', 'ask', 'eval'] as const;

export type KnowledgeTabPreferences = TabPreferences<KnowledgeTabPreference>;

export function createKnowledgePreferences(): KnowledgeTabPreferences {
  return createTabPreferences<KnowledgeTabPreference>({
    storageKey: PREF_KEYS.knowledgeActiveTab,
    defaultTab: 'browse',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}
