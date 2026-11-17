// Every key the sample app keeps in the browser (each prefixed with app.ts's `storagePrefix`). An app lists its
// own here before using one: `load`, `save`, `persisted` and `UrlTab` only take these.
export const PREF_KEYS = ['sidebar.open', 'sidebar.closedGroups', 'sidebar.width', 'gallery.tab', 'settings.tab', 'logs.tab', 'gallery.theme',
	// The memory graph viewer's (kit memory/graph): its view options, hidden types, fact filters, group, episodes,
	// detail-panel side and folded option sections.
	'graph.options', 'graph.hideNodes', 'graph.hideEdges', 'graph.edgeFilters', 'graph.group', 'graph.episodes',
	'graph.panelSide', 'graph.optionSections'] as const;

export type PrefKey = (typeof PREF_KEYS)[number];
