// The keys the shared UI kit keeps in the browser for the admin (each prefixed with app.ts's `storagePrefix`):
// the menu's state and the graph viewer's. The admin's own keys are in lib/preferences/keys.ts until its pages move to the kit's helpers.
export const PREF_KEYS = [
  'sidebar.open',
  'sidebar.closedGroups',
  'sidebar.width',
  'gallery.tab',
  'gallery.theme',
  // The memory graph viewer's (kit memory/graph, on the Memories page): its view options, hidden types, fact
  // filters, group, episodes, detail-panel side and folded option sections.
  'graph.options',
  'graph.hideNodes',
  'graph.hideEdges',
  'graph.edgeFilters',
  'graph.group',
  'graph.episodes',
  'graph.panelSide',
  'graph.optionSections'
] as const;

export type PrefKey = (typeof PREF_KEYS)[number];
