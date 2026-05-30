import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
import type { TableSortDirection } from '$lib/components/page/table/table-sort-utils';
import { allCatalogKinds, isRowAvailable } from './catalog-filter-ui';

export const PROVIDER_SORT_COLUMNS = ['online', 'provider', 'hosting', 'updated'] as const;
export type ProviderSortColumn = (typeof PROVIDER_SORT_COLUMNS)[number];

export const MODEL_SORT_COLUMNS = ['online', 'provider', 'model', 'kind', 'class', 'hosting', 'context'] as const;
export type ModelSortColumn = (typeof MODEL_SORT_COLUMNS)[number];

function compareStrings(a: string, b: string, direction: TableSortDirection): number {
  const cmp = a.localeCompare(b, undefined, { sensitivity: 'base' });
  return direction === 'asc' ? cmp : -cmp;
}

function compareNumbers(a: number | null, b: number | null, direction: TableSortDirection): number {
  const av = a ?? -1;
  const bv = b ?? -1;
  const cmp = av === bv ? 0 : av < bv ? -1 : 1;
  return direction === 'asc' ? cmp : -cmp;
}

export function sortProviders(
  rows: CatalogProviderRow[],
  sortBy: ProviderSortColumn,
  direction: TableSortDirection,
  configuredProviderIds: Set<string>
): CatalogProviderRow[] {
  const list = [...rows];
  list.sort((a, b) => {
    switch (sortBy) {
      case 'online': {
        const ao = configuredProviderIds.has(a.id) ? 1 : 0;
        const bo = configuredProviderIds.has(b.id) ? 1 : 0;
        return compareNumbers(ao, bo, direction);
      }
      case 'hosting':
        return compareStrings(a.hosting ?? '', b.hosting ?? '', direction);
      case 'updated':
        return compareStrings(a.metadata_updated_at ?? '', b.metadata_updated_at ?? '', direction);
      case 'provider':
      default:
        return compareStrings(a.display_name, b.display_name, direction);
    }
  });
  return list;
}

export function sortModels(
  rows: CatalogModelRow[],
  sortBy: ModelSortColumn,
  direction: TableSortDirection,
  providerLabels: Record<string, string>,
  configuredProviderIds: Set<string>
): CatalogModelRow[] {
  const list = [...rows];
  list.sort((a, b) => {
    switch (sortBy) {
      case 'online': {
        const ao = isRowAvailable(a, configuredProviderIds) ? 1 : 0;
        const bo = isRowAvailable(b, configuredProviderIds) ? 1 : 0;
        return compareNumbers(ao, bo, direction);
      }
      case 'provider': {
        const al = providerLabels[a.provider_id] ?? a.provider_id;
        const bl = providerLabels[b.provider_id] ?? b.provider_id;
        return compareStrings(al, bl, direction);
      }
      case 'kind': {
        const ak = allCatalogKinds(a)[0] ?? a.model_kind;
        const bk = allCatalogKinds(b)[0] ?? b.model_kind;
        return compareStrings(ak, bk, direction);
      }
      case 'class':
        return compareStrings(a.model_class ?? '', b.model_class ?? '', direction);
      case 'hosting':
        return compareStrings(a.hosting ?? '', b.hosting ?? '', direction);
      case 'context':
        return compareNumbers(
          typeof a.context_window === 'number' ? a.context_window : null,
          typeof b.context_window === 'number' ? b.context_window : null,
          direction
        );
      case 'model':
      default:
        return compareStrings(a.display_name, b.display_name, direction);
    }
  });
  return list;
}
