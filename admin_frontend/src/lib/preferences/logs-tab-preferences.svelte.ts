/**
 * Logs page primary-tab preference (`?tab=` + session storage), via the shared
 * `createTabPreferences` factory.
 *
 * The Logs page hosts two panes: the live log feed (`logs`, default) and the
 * Graph runs ledger (`runs`) — Graph runs moved here from its own route so it
 * reads as the Logs page's second tab. The log-feed filter preferences stay in
 * `logs-preferences.svelte.ts`; this module owns only the page-level tab pill.
 */
import { PREF_KEYS, type LogsPrimaryTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';

const ALLOWED: readonly LogsPrimaryTabPreference[] = ['logs', 'runs'] as const;

export type LogsTabPreferences = TabPreferences<LogsPrimaryTabPreference>;

export function createLogsTabPreferences(): LogsTabPreferences {
  return createTabPreferences<LogsPrimaryTabPreference>({
    storageKey: PREF_KEYS.logsPrimaryActiveTab,
    defaultTab: 'logs',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });
}
