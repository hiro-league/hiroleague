import {
  listCatalogModels,
  listCatalogProviders,
  listLocalCatalogModels,
  type CatalogModelFilters,
  type CatalogModelRow,
  type CatalogProviderRow
} from '$lib/api/catalog';
import { createActiveProvidersStore } from '$lib/catalog/active-providers/active-providers-store.svelte';
import {
  catalogReloadSuccessMessage,
  reloadCatalogAndRefetch
} from '$lib/catalog/catalog-reload';
import { preserveStickyAnchor } from '$lib/components/page/table/preserve-sticky-anchor';
import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
import { useTableSort } from '$lib/components/page/table/use-table-sort.svelte';
import { createCatalogPreferences } from '$lib/preferences/catalog-preferences.svelte';
import type { CatalogTabPreference } from '$lib/preferences/keys';
import type { ToastKind } from '$lib/ui/toast-types';
import {
  AVAILABILITY_FILTER_IDS,
  filterModelsByAvailability,
  HOSTING_FILTER_IDS,
  MODEL_KIND_FILTER_IDS,
  modelSupportsCatalogKind,
  parseCommaList,
  type AvailabilityFilterId,
  type HostingFilterId,
  type ModelKindFilterId
} from '../shared/catalog-filter-ui';
import {
  MODEL_SORT_COLUMNS,
  PROVIDER_SORT_COLUMNS,
  sortModels,
  sortProviders
} from '../shared/catalog-sort';

type Notify = (kind: ToastKind, message: string) => void;

export type CatalogController = ReturnType<typeof createCatalogController>;

function catalogModelDisplayNameMap(rows: CatalogModelRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    out[row.id] = row.display_name;
  }
  return out;
}

export function createCatalogController(notify: Notify) {
  const prefs = createCatalogPreferences();
  const activeProvidersStore = createActiveProvidersStore();

  const modelFilters = useTableFilters({
    keys: ['provider_id', 'model_class', 'model_kind', 'hosting', 'availability'] as const,
    urlSync: true
  });

  const providerSort = useTableSort({
    allowed: PROVIDER_SORT_COLUMNS,
    defaultBy: 'provider',
    defaultDirection: 'asc'
  });

  const modelSort = useTableSort({
    allowed: MODEL_SORT_COLUMNS,
    defaultBy: 'model',
    defaultDirection: 'asc',
    urlSync: true
  });

  let providers = $state<CatalogProviderRow[]>([]);
  let models = $state<CatalogModelRow[]>([]);
  let catalogVersion = $state<string | null>(null);
  let providersLoading = $state(true);
  let modelsLoading = $state(false);
  let providersError = $state<string | null>(null);
  let modelsError = $state<string | null>(null);
  let catalogReloadBusy = $state(false);
  /** All bundled models — used to resolve recommended_models ids to display names on the providers tab. */
  let catalogModelDisplayNames = $state<Record<string, string>>({});

  const providerLabels = $derived(
    providers.reduce<Record<string, string>>((acc, provider) => {
      acc[provider.id] = `${provider.display_name} (${provider.id})`;
      return acc;
    }, {})
  );

  const providerCounts = $derived(
    providers.reduce(
      (acc, provider) => {
        acc.total += 1;
        if (provider.hosting === 'cloud') acc.cloud += 1;
        if (provider.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  const recommendedCatalogModelIds = $derived(
    new Set(
      providers.flatMap((p) =>
        p.recommended_models ? Object.values(p.recommended_models).filter(Boolean) : []
      )
    )
  );

  const configuredWorkspaceProviderIds = $derived(activeProvidersStore.configuredProviderIds);

  const sortedProviders = $derived(
    sortProviders(
      providers,
      providerSort.sortBy,
      providerSort.direction,
      configuredWorkspaceProviderIds
    )
  );

  const filteredModels = $derived(
    filterModelsByAvailability(
      models,
      selectedAvailabilityFilters(),
      configuredWorkspaceProviderIds
    )
  );

  const sortedModels = $derived(
    sortModels(
      filteredModels,
      modelSort.sortBy,
      modelSort.direction,
      providerLabels,
      configuredWorkspaceProviderIds
    )
  );

  const hasModelFilters = $derived.by(() => {
    const f = modelFilters.filters;
    return Boolean(
      f.provider_id.trim() ||
        f.model_class.trim() ||
        f.model_kind.trim() ||
        f.hosting.trim() ||
        f.availability.trim()
    );
  });

  function selectedAvailabilityFilters(): AvailabilityFilterId[] {
    const selected = new Set(parseCommaList(modelFilters.filters.availability));
    return AVAILABILITY_FILTER_IDS.filter((id) => selected.has(id));
  }

  function selectedModelKinds(): ModelKindFilterId[] {
    const selected = new Set(parseCommaList(modelFilters.filters.model_kind));
    return MODEL_KIND_FILTER_IDS.filter((k) => selected.has(k));
  }

  function isModelKindSelected(kind: ModelKindFilterId): boolean {
    return parseCommaList(modelFilters.filters.model_kind).includes(kind);
  }

  function isHostingSelected(hosting: HostingFilterId): boolean {
    return parseCommaList(modelFilters.filters.hosting).includes(hosting);
  }

  function isAvailabilitySelected(availability: AvailabilityFilterId): boolean {
    return parseCommaList(modelFilters.filters.availability).includes(availability);
  }

  function catalogFetchFilters(): CatalogModelFilters {
    const kinds = selectedModelKinds();
    const out: CatalogModelFilters = {};
    const prov = modelFilters.filters.provider_id.trim();
    if (prov) out.provider_id = prov;
    const mc = modelFilters.filters.model_class.trim();
    if (mc) out.model_class = mc;
    const hostings = HOSTING_FILTER_IDS.filter((h) => isHostingSelected(h));
    if (hostings.length === 1) out.hosting = hostings[0];
    if (kinds.length === 1) out.model_kind = kinds[0];
    return out;
  }

  async function loadCatalogModelIndex() {
    try {
      const payload = await listCatalogModels();
      catalogModelDisplayNames = catalogModelDisplayNameMap(payload.data?.models ?? []);
      if (payload.data?.catalog_version) {
        catalogVersion = payload.data.catalog_version;
      }
    } catch {
      catalogModelDisplayNames = {};
    }
  }

  async function loadProviders() {
    providersLoading = true;
    providersError = null;
    try {
      const payload = await listCatalogProviders();
      providers = payload.data;
    } catch (err) {
      providersError = err instanceof Error ? err.message : 'Failed to load catalog providers.';
      providers = [];
    } finally {
      providersLoading = false;
    }
  }

  // Local in-process models (rerankers today) are merged into the browse as read-only
  // hosting:local rows. They have no model_class, so a class filter excludes them; the hosting
  // and provider/kind filters are applied here to mirror the catalog list.
  async function loadLocalModels(): Promise<CatalogModelRow[]> {
    if (modelFilters.filters.model_class.trim()) return [];
    const hostings = HOSTING_FILTER_IDS.filter((h) => isHostingSelected(h));
    if (hostings.length === 1 && hostings[0] !== 'local') return [];
    const kinds = selectedModelKinds();
    const rows = await listLocalCatalogModels(kinds.length === 1 ? kinds[0] : undefined);
    let list = rows;
    if (kinds.length > 1) {
      list = list.filter((m) => kinds.some((k) => modelSupportsCatalogKind(m, k)));
    }
    const prov = modelFilters.filters.provider_id.trim();
    if (prov) list = list.filter((m) => m.provider_id === prov);
    return list;
  }

  async function loadModels() {
    modelsLoading = true;
    modelsError = null;
    try {
      const fetchFilters = catalogFetchFilters();
      const kinds = selectedModelKinds();
      const [payload, localRows] = await Promise.all([
        listCatalogModels(fetchFilters),
        loadLocalModels()
      ]);
      catalogVersion = payload.data.catalog_version;
      let list = payload.data.models;
      if (kinds.length > 1) {
        list = list.filter((m) => kinds.some((k) => modelSupportsCatalogKind(m, k)));
      }
      models = [...list, ...localRows];
    } catch (err) {
      modelsError = err instanceof Error ? err.message : 'Failed to load catalog models.';
      models = [];
    } finally {
      modelsLoading = false;
    }
  }

  async function reloadBundledCatalog() {
    catalogReloadBusy = true;
    try {
      const result = await reloadCatalogAndRefetch([]);
      notify('success', catalogReloadSuccessMessage(result.reload));
      providers = result.providers;
      providersError = null;
      const indexRows: CatalogModelRow[] = [];
      for (const list of Object.values(result.modelsByKind)) {
        if (list) indexRows.push(...list);
      }
      catalogModelDisplayNames = catalogModelDisplayNameMap(indexRows);
      await activeProvidersStore.load({ silent: true });
      if (prefs.activeTab === 'models') {
        await loadModels();
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      catalogReloadBusy = false;
    }
  }

  async function switchTab(tab: CatalogTabPreference) {
    await prefs.setActiveTab(tab);
    void activeProvidersStore.load({ silent: true });
    if (tab === 'models' && models.length === 0 && !modelsLoading) {
      await loadModels();
    }
  }

  async function refreshCatalogProviders() {
    await Promise.all([loadProviders(), loadCatalogModelIndex()]);
    await activeProvidersStore.load({ silent: true });
  }

  async function openModelsForProvider(providerId: string) {
    modelFilters.set('provider_id', providerId);
    await prefs.setActiveTab('models');
    await loadModels();
  }

  async function applyModelFilters() {
    if (prefs.activeTab !== 'models') {
      await prefs.setActiveTab('models');
    }
    // Filter changes resize the rendered list; the anchor helper keeps the
    // sticky table head at the same viewport y so we don't snap back to top.
    await preserveStickyAnchor(loadModels);
  }

  async function clearModelFilters() {
    modelFilters.reset();
    await applyModelFilters();
  }

  async function toggleModelKindFilter(kind: ModelKindFilterId) {
    const set = new Set(parseCommaList(modelFilters.filters.model_kind));
    if (set.has(kind)) {
      set.delete(kind);
    } else {
      set.add(kind);
    }
    modelFilters.set('model_kind', [...set].join(','));
    await applyModelFilters();
  }

  async function toggleHostingFilter(hosting: HostingFilterId) {
    const set = new Set(parseCommaList(modelFilters.filters.hosting));
    if (set.has(hosting)) {
      set.delete(hosting);
    } else {
      set.add(hosting);
    }
    modelFilters.set('hosting', [...set].join(','));
    await applyModelFilters();
  }

  function toggleAvailabilityFilter(availability: AvailabilityFilterId) {
    const set = new Set(parseCommaList(modelFilters.filters.availability));
    if (set.has(availability)) {
      set.delete(availability);
    } else {
      set.add(availability);
    }
    modelFilters.set('availability', [...set].join(','));
  }

  async function initialize() {
    prefs.initialize();
    await Promise.all([loadProviders(), loadCatalogModelIndex(), activeProvidersStore.load()]);
    if (prefs.activeTab === 'models') {
      await loadModels();
    }
  }

  return {
    get activeTab() {
      return prefs.activeTab;
    },
    get providers() {
      return providers;
    },
    get sortedProviders() {
      return sortedProviders;
    },
    get models() {
      return models;
    },
    get filteredModels() {
      return filteredModels;
    },
    get sortedModels() {
      return sortedModels;
    },
    get catalogVersion() {
      return catalogVersion;
    },
    get providersLoading() {
      return providersLoading;
    },
    get modelsLoading() {
      return modelsLoading;
    },
    get providersError() {
      return providersError;
    },
    get modelsError() {
      return modelsError;
    },
    get catalogReloadBusy() {
      return catalogReloadBusy;
    },
    get providerLabels() {
      return providerLabels;
    },
    get providerCounts() {
      return providerCounts;
    },
    get recommendedCatalogModelIds() {
      return recommendedCatalogModelIds;
    },
    get catalogModelDisplayNames() {
      return catalogModelDisplayNames;
    },
    get configuredWorkspaceProviderIds() {
      return configuredWorkspaceProviderIds;
    },
    get activeProvidersStore() {
      return activeProvidersStore;
    },
    get modelFilters() {
      return modelFilters;
    },
    get providerSort() {
      return providerSort;
    },
    get modelSort() {
      return modelSort;
    },
    get hasModelFilters() {
      return hasModelFilters;
    },
    isModelKindSelected,
    isHostingSelected,
    isAvailabilitySelected,
    switchTab,
    refreshCatalogProviders,
    openModelsForProvider,
    applyModelFilters,
    clearModelFilters,
    toggleModelKindFilter,
    toggleHostingFilter,
    toggleAvailabilityFilter,
    loadModels,
    reloadBundledCatalog,
    initialize
  };
}
