/**
 * Permissions phase 2: the core's own features, by id, so each admin page and tab can say which one opens it.
 *
 * A permission is `feature.action`, or `area.feature.action` when an area groups several features (`ai.providers`):
 * a feature's id carries its area. The core declares the features and their actions (source `hiroleague`,
 * domain/core_features.py) and works out each one's level for a person (`/auth/me`'s `levels`): only a grant that
 * reaches everyone's opens a page. This file holds no rule of its own.
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
