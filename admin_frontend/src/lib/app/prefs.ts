// The keys the shared UI kit keeps in the browser for the admin (each prefixed with app.ts's `storagePrefix`):
// the menu's state. The admin's own keys are in lib/preferences/keys.ts until its pages move to the kit's helpers.
export const PREF_KEYS = ['sidebar.open', 'sidebar.closedGroups', 'sidebar.width', 'gallery.theme'] as const;

export type PrefKey = (typeof PREF_KEYS)[number];
