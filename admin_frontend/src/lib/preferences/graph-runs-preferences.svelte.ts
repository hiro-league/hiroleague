import { PREF_KEYS } from './keys';
import { readLocalBoolean, writeLocalBoolean } from './storage';

/** Graph Runs page UI preferences (localStorage-backed layout toggles). */
export function createGraphRunsPreferences() {
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

export type GraphRunsPreferences = ReturnType<typeof createGraphRunsPreferences>;
