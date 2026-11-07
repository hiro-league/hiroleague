import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';

/**
 * Why a saved model id can't run, as the model pickers show it under the selected model.
 *
 * Replaces the old `includeUnknownModel`, which injected a saved id that is no longer in the catalog
 * as an ordinary picker row (display_name = the id), so a removed model (e.g. after the Nov 2026
 * models refresh) looked like a normal choice while the server could not resolve it and Hiro
 * answered every chat with the "no model" reply. The picker now derives the problem from the live
 * catalog for every model path, and after a catalog reload too.
 */
export type SelectedModelIssue =
  /** The id is in neither the bundled catalog nor the local-model list. */
  | { kind: 'missing'; message: string }
  /** The model exists, but its provider is not set up in Active Providers. */
  | { kind: 'provider_inactive'; message: string };

export type SelectedModelIssueInput = {
  selectedId: string | null | undefined;
  /** Picker options for this kind (catalog rows, plus local rows for embedding / rerank). */
  catalogModels: CatalogModelRow[];
  /** False until the catalog lists have loaded — an empty list then means "unknown", not "missing". */
  catalogLoaded: boolean;
  /** Provider ids set up in this workspace for this model kind. */
  activeProviderIds: Set<string>;
  /** False until the Active Providers list has loaded. */
  activeProvidersResolved: boolean;
  /** For the provider's display name in the message; falls back to the provider id. */
  providers?: CatalogProviderRow[];
};

export function missingModelMessage(id: string): string {
  return `${id} is no longer available. Pick another model.`;
}

export function inactiveProviderMessage(providerName: string): string {
  return `${providerName} is not set up in Active Providers, so this model can't run. Add the provider or pick another model.`;
}

export function selectedModelIssue(input: SelectedModelIssueInput): SelectedModelIssue | null {
  const id = input.selectedId?.trim();
  if (!id || !input.catalogLoaded) return null;
  const row = input.catalogModels.find((model) => model.id === id);
  if (!row) return { kind: 'missing', message: missingModelMessage(id) };
  const providerId = row.provider_id?.trim();
  if (input.activeProvidersResolved && providerId && !input.activeProviderIds.has(providerId)) {
    const name =
      input.providers?.find((provider) => provider.id === providerId)?.display_name?.trim() ||
      providerId;
    return { kind: 'provider_inactive', message: inactiveProviderMessage(name) };
  }
  return null;
}
