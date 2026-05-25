/**
 * Graph Runs page preferences:
 *  - Primary tab (`runs` vs `memories`) — URL `?tab=` + session, via the shared
 *    `createTabPreferences` factory (plan §2.2 / Phase 2 exit criterion 4a).
 *  - `runDetailCardsExpanded` — localStorage-backed run-detail layout toggle
 *    (unchanged; not a page-level tab pref).
 *
 * The dynamic per-record subtab strip (open run inspectors) stays feature-local
 * and is keyed by `?run=<id>` on the controller, not by this module.
 */
import { PREF_KEYS, type GraphRunsPrimaryTabPreference } from './keys';
import { createTabPreferences, type TabPreferences } from './create-tab-preferences.svelte';
import { readLocalBoolean, writeLocalBoolean } from './storage';

const ALLOWED: readonly GraphRunsPrimaryTabPreference[] = ['runs', 'memories'] as const;

export type GraphRunsPreferences = TabPreferences<GraphRunsPrimaryTabPreference> & {
  readonly runDetailCardsExpanded: boolean;
  toggleRunDetailCards: () => void;
};

export function createGraphRunsPreferences(): GraphRunsPreferences {
  const tabs = createTabPreferences<GraphRunsPrimaryTabPreference>({
    storageKey: PREF_KEYS.graphRunsActiveTab,
    defaultTab: 'runs',
    allowed: ALLOWED,
    omitDefaultFromUrl: true
  });

  let runDetailCardsExpanded = $state(true);

  function initialize() {
    tabs.initialize();
    runDetailCardsExpanded = readLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, true);
  }

  function toggleRunDetailCards() {
    runDetailCardsExpanded = !runDetailCardsExpanded;
    writeLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, runDetailCardsExpanded);
  }

  return {
    get activeTab() {
      return tabs.activeTab;
    },
    setActiveTab: tabs.setActiveTab,
    syncActiveTabFromUrl: tabs.syncActiveTabFromUrl,
    get runDetailCardsExpanded() {
      return runDetailCardsExpanded;
    },
    initialize,
    toggleRunDetailCards
  };
}
