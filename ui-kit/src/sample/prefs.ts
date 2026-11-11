// Every key the sample app keeps in the browser (each prefixed with app.ts's `storagePrefix`). An app lists its
// own here before using one: `load`, `save`, `persisted` and `UrlTab` only take these.
export const PREF_KEYS = ['sidebar.open', 'sidebar.closedGroups', 'sidebar.width', 'gallery.tab'] as const;

export type PrefKey = (typeof PREF_KEYS)[number];
