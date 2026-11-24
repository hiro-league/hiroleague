/**
 * Permissions phase 2: the core's own features, and how a person's keys in them open the admin's pages.
 *
 * A permission is `feature.action`, or `area.feature.action` when an area groups several features (`ai.providers`):
 * a feature's id carries its area. The core declares the features and their actions (source `hiroleague`); this file
 * names only the ids, so each page and tab can say which feature opens it.
 *
 * Only a grant that reaches everyone's opens a page: one for their own things (`conversations.see:own`) is used from
 * a chat channel or a device, never the admin.
 */
import type { Access } from '$lib/app/api';

export const CORE_FEATURES = [
  'assistant',
  'assistant.characters',
  'conversations',
  'memories',
  'knowledge',
  'ai.providers',
  'ai.profiles',
  'ai.images',
  'extensions',
  'devices',
  'logs',
  'logs.runs',
  'logs.usage',
  'server',
  'settings'
] as const;

export type CoreFeature = (typeof CORE_FEATURES)[number];

/** Every feature that opens a page of the admin: all but talking to Hiro, which is a chat channel's or a device's. */
export const ADMIN_FEATURES: CoreFeature[] = CORE_FEATURES.filter((f) => f !== 'assistant');

const SEE = 'see';
const OWN = ':own';

/**
 * Each feature's level for the pages, from a person's keys in the core: "use" with any action beyond `see`, "see"
 * with only that, else "no". A key for their own things counts for nothing here.
 */
export function accessFromKeys(keys: Iterable<string>, features: readonly string[] = CORE_FEATURES): Record<string, Access> {
  const held = new Set([...keys].filter((k) => !k.endsWith(OWN)));
  const out: Record<string, Access> = {};
  for (const f of features) {
    const actions = [...held].filter((k) => k.slice(0, k.lastIndexOf('.')) === f).map((k) => k.slice(k.lastIndexOf('.') + 1));
    out[f] = actions.some((a) => a !== SEE) ? 'use' : actions.includes(SEE) ? 'see' : 'no';
  }
  return out;
}

/**
 * The tabs of a page this person may open: each tab names the core feature that opens it. With none of them, every
 * tab (the page itself is refused before it draws).
 */
export function tabsFor<T extends { id: string }>(
  tabs: readonly T[],
  featureOf: (id: T['id']) => CoreFeature,
  access: Readonly<Record<string, Access>> | null | undefined
): T[] {
  const shown = tabs.filter((t) => (access?.[featureOf(t.id)] ?? 'no') !== 'no');
  return shown.length ? shown : [...tabs];
}

/** Every feature at "use": the owner, and today's role whose admin switch is on. */
export const fullAccess = (): Record<string, Access> => Object.fromEntries(CORE_FEATURES.map((f) => [f, 'use' as Access]));
