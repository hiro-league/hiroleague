/**
 * Settings search controller. Holds the query + active-match cursor; derives the match list and
 * per-tab counts from the (data-only) search index, so counts cover every tab while only the active
 * one is mounted. It owns NO DOM side effects — the Settings page watches `activeMatch` and performs
 * the jump (switch tab, force advanced on, expand sections, scroll + highlight). Search is gated to
 * the clean state by the page (disabled + cleared while there are unsaved edits).
 */
import type { PreferencesSchemaMap } from '$lib/features/preferences/shared/preferences-schema';
import type { PreferenceTabId } from '$lib/features/preferences/shared/preferences-tabs';
import { isPreferenceTabActive } from '$lib/features/preferences/shared/preferences-tabs';
import {
  buildPrefSearchIndex,
  countPrefMatchesByTab,
  filterPrefSearch,
  type PrefSearchEntry
} from '$lib/features/preferences/shared/preferences-search-index';

export function createPreferencesSearch(getSchema: () => PreferencesSchemaMap) {
  let query = $state('');
  // Cursor into `matches`. -1 = no active match (blank query or no results).
  let activeIndex = $state(-1);

  // Drop entries for tabs whose feature is hidden, so search never jumps to a gated tab. The index
  // builder stays feature-agnostic (complete + unit-tested); gating is applied here at the edge.
  const index = $derived(
    buildPrefSearchIndex(getSchema()).filter((entry) => isPreferenceTabActive(entry.tabId))
  );
  // Derived IN the controller (reads `query` in-scope) so it tracks reliably when consumed via the
  // `active` getter — a page-level `$derived(!!search.query.trim())` reading the raw-state getter
  // across modules did not register the dependency and never updated.
  const active = $derived(query.trim().length > 0);
  const matches = $derived(filterPrefSearch(index, query));
  const countsByTab = $derived<Partial<Record<PreferenceTabId, number>>>(
    countPrefMatchesByTab(matches)
  );
  const activeMatch = $derived<PrefSearchEntry | null>(
    activeIndex >= 0 && activeIndex < matches.length ? matches[activeIndex] : null
  );

  function setQuery(next: string) {
    query = next;
    // Auto-select the first match so counts + the n/N indicator update and the page jumps to it.
    activeIndex = next.trim() ? 0 : -1;
  }

  function step(delta: number) {
    const count = matches.length;
    if (count === 0) {
      activeIndex = -1;
      return;
    }
    const base = activeIndex < 0 ? 0 : activeIndex;
    activeIndex = (base + delta + count) % count;
  }

  function select(index: number) {
    if (index >= 0 && index < matches.length) activeIndex = index;
  }

  function clear() {
    query = '';
    activeIndex = -1;
  }

  return {
    get query() {
      return query;
    },
    /** True while a (non-blank) query is active — drives clean UI gating like the compact header. */
    get active() {
      return active;
    },
    get matches() {
      return matches;
    },
    get countsByTab() {
      return countsByTab;
    },
    get activeMatch() {
      return activeMatch;
    },
    /** 1-based position of the active match, 0 when none. */
    get position() {
      return activeMatch ? activeIndex + 1 : 0;
    },
    get total() {
      return matches.length;
    },
    setQuery,
    next: () => step(1),
    prev: () => step(-1),
    select,
    clear
  };
}

export type PreferencesSearch = ReturnType<typeof createPreferencesSearch>;
