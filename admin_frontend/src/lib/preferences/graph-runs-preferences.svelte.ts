/**
 * Graph Runs UI preference: `runDetailCardsExpanded` — a localStorage-backed
 * run-detail layout toggle (expanded vs collapsed metric/ledger cards).
 *
 * The page-level primary tab pill moved to the Logs page (Graph runs is now its
 * second tab) — see `logs-tab-preferences.svelte.ts`. The dynamic per-record
 * subtab strip (open run inspectors) stays feature-local, keyed by `?run=<id>`
 * on the controller.
 */
import { PREF_KEYS } from './keys';
import { readLocalBoolean, writeLocalBoolean } from './storage';

export type GraphRunsPreferences = {
  readonly runDetailCardsExpanded: boolean;
  initialize: () => void;
  toggleRunDetailCards: () => void;
};

export function createGraphRunsPreferences(): GraphRunsPreferences {
  let runDetailCardsExpanded = $state(true);

  function initialize() {
    runDetailCardsExpanded = readLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, true);
  }

  function toggleRunDetailCards() {
    runDetailCardsExpanded = !runDetailCardsExpanded;
    writeLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, runDetailCardsExpanded);
  }

  return {
    get runDetailCardsExpanded() {
      return runDetailCardsExpanded;
    },
    initialize,
    toggleRunDetailCards
  };
}
