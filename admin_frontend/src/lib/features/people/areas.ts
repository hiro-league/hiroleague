/**
 * Permissions phase 2: a source's features in their areas, as Roles and Compare show them. A permission is
 * `feature.action` or `area.feature.action`; a feature's id carries its area (`ai.providers`), and a name may be a
 * feature and an area at once (`assistant` beside `assistant.characters`).
 */
import type { AccessFeature } from '$lib/api/people';

export type AreaGroup = { area: string | null; name: string; features: AccessFeature[] };

/**
 * Features in their areas, in declaration order: a feature with no area is a group of its own (area null); the
 * features of an area (its own id, then `area.<feature>`) are one group under the area's name.
 */
export function groupByArea(features: readonly AccessFeature[], areas: Readonly<Record<string, string>>): AreaGroup[] {
  const out: AreaGroup[] = [];
  for (const feature of features) {
    const head = feature.id.split('.')[0];
    const area = head in areas ? head : null;
    const last = out.at(-1);
    if (area !== null && last?.area === area) last.features.push(feature);
    else out.push({ area, name: area !== null ? areas[area] : feature.name, features: [feature] });
  }
  return out;
}
