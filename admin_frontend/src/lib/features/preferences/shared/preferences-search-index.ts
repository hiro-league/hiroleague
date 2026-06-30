/**
 * Settings search index — pure, data-driven (no mounted components), so per-tab match counts and
 * cross-tab navigation work while only the active tab is rendered. An entry is built for every
 * EDITABLE preference path: its display `title` (the backend `Field(title=…)`, the same string the
 * field widget renders) and its `tabId` (from `tabForPreferencePath`). Read-only enrichment fields
 * and image-lab-only fields (`preferencesSaveSkip`) are excluded — they aren't surfaced on the
 * Settings tabs.
 */
import type { PreferenceTabId } from './preferences-tabs';
import {
  PREFERENCE_FIELD_ORDER,
  PREFERENCE_SECTION_ORDER,
  PREFERENCE_TABS,
  sectionForPreferencePath,
  tabForPreferencePath
} from './preferences-tabs';
import type { PreferencesSchemaMap } from './preferences-schema';

export type PrefSearchEntry = {
  path: string;
  title: string;
  tabId: PreferenceTabId;
  /** Human tab name (e.g. "Memory") for the autocomplete locator line. */
  tabLabel: string;
  /** Card/section title (e.g. "Default models"), or null when unmapped. */
  section: string | null;
};

const TAB_ORDER = new Map<PreferenceTabId, number>(PREFERENCE_TABS.map((tab, i) => [tab.id, i]));
const TAB_LABEL = new Map<PreferenceTabId, string>(PREFERENCE_TABS.map((tab) => [tab.id, tab.label]));
const SECTION_RANK = new Map<string, number>(PREFERENCE_SECTION_ORDER.map((s, i) => [s, i]));
const FIELD_RANK = new Map<string, number>(PREFERENCE_FIELD_ORDER.map((p, i) => [p, i]));

// Section rank (tab order + card order). Unmapped sections sort last, still grouped by tab.
function sectionRank(entry: PrefSearchEntry): number {
  const r = entry.section != null ? SECTION_RANK.get(entry.section) : undefined;
  return r ?? 1000 + (TAB_ORDER.get(entry.tabId) ?? 0);
}

// Field rank within its card (markup order). Fields not in the list sort after the listed ones in
// their section, in schema order (kept by the stable sort).
function fieldRank(path: string): number {
  return FIELD_RANK.get(path) ?? Number.MAX_SAFE_INTEGER;
}

/** Build the flat searchable entry list from the field schema map. */
export function buildPrefSearchIndex(schema: PreferencesSchemaMap): PrefSearchEntry[] {
  const out: PrefSearchEntry[] = [];
  for (const meta of Object.values(schema)) {
    if (meta.readOnly || meta.preferencesSaveSkip) continue;
    const tabId = tabForPreferencePath(meta.path);
    if (!tabId) continue;
    out.push({
      path: meta.path,
      title: meta.title?.trim() || meta.path,
      tabId,
      tabLabel: TAB_LABEL.get(tabId) ?? tabId,
      section: sectionForPreferencePath(meta.path)
    });
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
 * Filter the index by query, ordered to follow the page's visual layout: tab → section (card) →
 * field order within the card. This makes arrow navigation move top-to-bottom as rendered, not in
 * the schema's model-definition order.
 */
export function filterPrefSearch(index: PrefSearchEntry[], query: string): PrefSearchEntry[] {
  if (!query.trim()) return [];
  return index
    .filter((entry) => matchesPrefQuery(entry, query))
    .sort((a, b) => sectionRank(a) - sectionRank(b) || fieldRank(a.path) - fieldRank(b.path));
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
