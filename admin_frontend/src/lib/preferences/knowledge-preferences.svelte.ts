import { PREF_KEYS, type KnowledgeTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly KnowledgeTabPreference[] = ['ingest', 'browse', 'ask'] as const;

export function createKnowledgePreferences(): TabPreferences<KnowledgeTabPreference> {
  return createTabPreferences<KnowledgeTabPreference>({
    storageKey: PREF_KEYS.knowledgeActiveTab,
    defaultTab: 'ingest',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}
