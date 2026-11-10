/**
 * Names a `provider:model` id for a one-line profile summary (Phase 7b step 5): the catalog's display
 * name and the provider's label when the catalog has them, else the raw id parts (local and plan-tool
 * models aren't catalog rows). Pure.
 */
import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
import { rawModelNamer, type ModelNamer } from './hiro-jobs';

export function catalogModelNamer(
  models: readonly CatalogModelRow[],
  providers: readonly Pick<CatalogProviderRow, 'id' | 'display_name'>[]
): ModelNamer {
  const modelNames = new Map(models.map((m) => [m.id, m.display_name]));
  const providerNames = new Map(providers.map((p) => [p.id, p.display_name]));
  return (model) => {
    const raw = rawModelNamer(model);
    return {
      provider: providerNames.get(raw.provider) || raw.provider,
      model: modelNames.get(model) || raw.model
    };
  };
}
