/**
 * Settings search index — pure, data-driven (no mounted components), so per-tab match counts and
 * cross-tab navigation work while only the active tab is rendered. An entry is built for every
 * EDITABLE preference path: its display `title` (the backend `Field(title=…)`, the same string the
 * field widget renders) and its `tabId` (from `tabForPreferencePath`). Read-only enrichment fields
 * and image-lab-only fields (`preferencesSaveSkip`) are excluded — they aren't surfaced on the
 * Settings tabs.
 */
import type { PreferenceTabId } from './preferences-tabs';
import { PREFERENCE_TABS, tabForPreferencePath } from './preferences-tabs';
import type { PreferencesSchemaMap } from './preferences-schema';

export type PrefSearchEntry = {
  path: string;
  title: string;
  tabId: PreferenceTabId;
};

const TAB_ORDER = new Map<PreferenceTabId, number>(PREFERENCE_TABS.map((tab, i) => [tab.id, i]));

/** Build the flat searchable entry list from the field schema map. */
export function buildPrefSearchIndex(schema: PreferencesSchemaMap): PrefSearchEntry[] {
  const out: PrefSearchEntry[] = [];
  for (const meta of Object.values(schema)) {
    if (meta.readOnly || meta.preferencesSaveSkip) continue;
    const tabId = tabForPreferencePath(meta.path);
    if (!tabId) continue;
    out.push({ path: meta.path, title: meta.title?.trim() || meta.path, tabId });
  }
  return out;
}

/** Case-insensitive token-AND match over the entry's title + dotted path. */
export function matchesPrefQuery(entry: PrefSearchEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return false;
  const haystack = `${entry.title} ${entry.path}`.toLowerCase();
  return q.split(/\s+/).every((token) => haystack.includes(token));
}

/**
 * Filter the index by query, ordered for arrow navigation: by tab (the tab strip's left-to-right
 * order) then by schema order within a tab (Array.sort is stable, so the index order is preserved).
 */
export function filterPrefSearch(index: PrefSearchEntry[], query: string): PrefSearchEntry[] {
  if (!query.trim()) return [];
  return index
    .filter((entry) => matchesPrefQuery(entry, query))
    .sort((a, b) => (TAB_ORDER.get(a.tabId) ?? 0) - (TAB_ORDER.get(b.tabId) ?? 0));
}

/** Count matches per tab, for the tab-strip count badges. */
export function countPrefMatchesByTab(
  matches: PrefSearchEntry[]
): Partial<Record<PreferenceTabId, number>> {
  const counts: Partial<Record<PreferenceTabId, number>> = {};
  for (const match of matches) {
    counts[match.tabId] = (counts[match.tabId] ?? 0) + 1;
  }
  return counts;
}
