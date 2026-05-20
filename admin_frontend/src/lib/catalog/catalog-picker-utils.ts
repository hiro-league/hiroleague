import type { CatalogModelRow } from '$lib/api/catalog';
import type { ModelTuning } from '$lib/api/preferences';

/** ISO date for sorting models newest-first (release date, then pricing refresh). */
export function catalogModelSortDate(model: CatalogModelRow): string {
  const released = model.released_at;
  if (typeof released === 'string' && released.trim()) {
    return released.trim();
  }
  const raw = model.pricing?.pricing_updated_at;
  return typeof raw === 'string' ? raw.trim() : '';
}

export function sortCatalogModelsByDateDesc(models: CatalogModelRow[]): CatalogModelRow[] {
  return models.slice().sort((a, b) => {
    const dateCmp = catalogModelSortDate(b).localeCompare(catalogModelSortDate(a));
    if (dateCmp !== 0) return dateCmp;
    return a.display_name.localeCompare(b.display_name);
  });
}

/** True when catalog row declares ``reasoning`` in ``features`` (bundled catalog.yaml). */
export function isThinkingCatalogModel(model: CatalogModelRow): boolean {
  return (model.features ?? []).includes('reasoning');
}

export type CatalogPickerProvider = {
  id: string;
  display_name: string;
};

export function sortCatalogProvidersOnlineFirst<T extends CatalogPickerProvider>(
  providers: T[],
  isOnline: (providerId: string) => boolean
): T[] {
  return providers.slice().sort((a, b) => {
    const aOnline = isOnline(a.id);
    const bOnline = isOnline(b.id);
    if (aOnline !== bOnline) return aOnline ? -1 : 1;
    return a.display_name.localeCompare(b.display_name);
  });
}

export function formatTuningProfileSummary(profile: ModelTuning): string {
  const parts = [`temp ${profile.temperature}`, `max tokens ${profile.max_tokens.toLocaleString()}`];
  if (profile.thinking) {
    parts.push(`thinking ${profile.thinking}`);
  } else {
    parts.push('thinking: model default');
  }
  return parts.join(' · ');
}
