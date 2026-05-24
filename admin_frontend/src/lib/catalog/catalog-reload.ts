import {
  listCatalogModels,
  listCatalogProviders,
  reloadModelCatalog,
  type CatalogModelRow,
  type CatalogProviderRow,
  type CatalogReloadData
} from '$lib/api/catalog';

export type CatalogModelKind = 'chat' | 'stt' | 'tts' | 'embedding';

export type CatalogRefetchResult = {
  reload: CatalogReloadData;
  modelsByKind: Partial<Record<CatalogModelKind, CatalogModelRow[]>>;
  providers: CatalogProviderRow[];
};

const DEFAULT_MODEL_KINDS: readonly CatalogModelKind[] = ['chat', 'stt', 'tts', 'embedding'];

/** Reload bundled catalog on the server, then parallel-fetch model lists and providers. */
export async function reloadCatalogAndRefetch(
  modelKinds: readonly CatalogModelKind[] = DEFAULT_MODEL_KINDS
): Promise<CatalogRefetchResult> {
  const reloadPayload = await reloadModelCatalog();
  const modelRequests = modelKinds.map((kind) =>
    listCatalogModels({ model_kind: kind }).then((response) => [kind, response.data.models] as const)
  );
  const [modelResults, providersPayload] = await Promise.all([
    Promise.all(modelRequests),
    listCatalogProviders()
  ]);
  const modelsByKind: Partial<Record<CatalogModelKind, CatalogModelRow[]>> = {};
  for (const [kind, models] of modelResults) {
    modelsByKind[kind] = models;
  }
  return {
    reload: reloadPayload.data,
    modelsByKind,
    providers: providersPayload.data
  };
}

export function catalogReloadSuccessMessage(reload: CatalogReloadData): string {
  return `Catalog v${reload.catalog_version} reloaded (${reload.provider_count} providers, ${reload.model_count} models).`;
}
