import type { CatalogModelRow } from '$lib/api/catalog';

/** Ensure a saved model id appears in picker options even when absent from the bundled catalog. */
export function includeUnknownModel(
  models: CatalogModelRow[],
  id: string,
  modelKind: CatalogModelRow['model_kind']
): CatalogModelRow[] {
  if (models.some((model) => model.id === id)) return models;
  const [providerId = 'unknown'] = id.split(':', 1);
  return [
    ...models,
    {
      id,
      provider_id: providerId || 'unknown',
      display_name: id,
      model_kind: modelKind
    }
  ];
}
