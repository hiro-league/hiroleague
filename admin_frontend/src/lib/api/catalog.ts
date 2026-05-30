import { apiRequest, type ApiResponse } from './client';

/** Preset voice id for a provider's bundled TTS API (matches catalog.yaml tts_voices). */
export type CatalogTtsVoiceRow = {
  id: string;
  display_name?: string | null;
  description?: string | null;
};

/** Editorial free-tier / trial note for a catalog provider (matches catalog.yaml free_offers). */
export type CatalogProviderFreeOffer = {
  label: string;
  summary: string;
  /** ISO YYYY-MM-DD — when this offer note was last verified. */
  updated_at: string;
  details?: string | null;
  details_url?: string | null;
};

export type CatalogProviderRow = {
  id: string;
  display_name: string;
  hosting: 'cloud' | 'local' | string;
  credential_env_keys?: string[];
  docs_url?: string | null;
  default_base_url?: string | null;
  recommended_models?: Record<string, string>;
  /** Curated presets for vendor TTS; empty when provider has no integrated speech API in Hiro. */
  tts_voices?: CatalogTtsVoiceRow[];
  /** Editorial trial / free-tier notes shown in admin provider tables. */
  free_offers?: CatalogProviderFreeOffer[];
  metadata_updated_at?: string | null;
  notes?: string | null;
};

export type CatalogModelRow = {
  id: string;
  provider_id: string;
  display_name: string;
  model_kind: 'chat' | 'tts' | 'stt' | 'embedding' | 'image_gen' | string;
  /** Additional Hiro purposes beyond ``model_kind`` (e.g. chat row also valid for STT). */
  extra_kinds?: string[];
  model_class?: string | null;
  hosting?: 'cloud' | 'local' | string | null;
  context_window?: number | null;
  modalities?: string[];
  features?: string[];
  tags?: string[];
  pricing?: Record<string, unknown> | null;
  /** Vendor model/API launch date (ISO YYYY-MM-DD) from bundled catalog.yaml. */
  released_at?: string | null;
  deprecated_since?: string | null;
  replacement_id?: string | null;
  notes?: string | null;
  /** "catalog" (default) or "local" — local in-process models merged into the browse. */
  source?: 'catalog' | 'local';
  /** Local rows only: per-workspace download status (availability axis = downloaded). */
  downloaded?: boolean;
  size_label?: string | null;
  languages?: string | null;
  /** Local rows only: free to run (no per-token cost) → pricing shows a Free indicator. */
  free?: boolean;
  /** Local rows only: where/how to make it available when not downloaded (kind-specific). */
  manage_hint?: string | null;
};

export type CatalogModelsResponse = {
  catalog_version: string;
  models: CatalogModelRow[];
};

export type ActiveProviderRow = {
  provider_id: string;
  display_name: string;
  hosting: 'cloud' | 'local' | string;
  auth_method: string;
  available_model_count: number;
  has_chat: boolean;
  has_tts: boolean;
  has_stt: boolean;
  has_embedding: boolean;
  has_rerank: boolean;
};

export type AddableProviderRow = {
  id: string;
  display_name: string;
};

export type CatalogReloadData = {
  catalog_version: string;
  provider_count: number;
  model_count: number;
};

export type CatalogModelFilters = {
  provider_id?: string;
  model_kind?: string;
  model_class?: string;
  hosting?: string;
};

function queryString(params: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value && value.trim()) {
      query.set(key, value);
    }
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

export async function listCatalogProviders(hosting?: string): Promise<ApiResponse<CatalogProviderRow[]>> {
  return apiRequest<CatalogProviderRow[]>(`/catalog/providers${queryString({ hosting })}`);
}

export async function listCatalogModels(
  filters: CatalogModelFilters = {}
): Promise<ApiResponse<CatalogModelsResponse>> {
  return apiRequest<CatalogModelsResponse>(`/catalog/models${queryString(filters)}`);
}

export async function reloadModelCatalog(): Promise<ApiResponse<CatalogReloadData>> {
  return apiRequest<CatalogReloadData>('/catalog/reload', { method: 'POST' });
}

/** Local in-process models, mapped into CatalogModelRow shape for the browse. */
export type LocalModelApiRow = {
  id: string;
  provider_id: string;
  display_name: string;
  model_kind: string;
  hosting: string;
  backend: string;
  size_label: string;
  languages: string;
  description: string;
  context_window: number | null;
  modalities: string[];
  features: string[];
  free: boolean;
  downloaded: boolean;
  manage_hint: string;
  source: string;
};

export async function listLocalCatalogModels(modelKind?: string): Promise<CatalogModelRow[]> {
  const payload = await apiRequest<{ models: LocalModelApiRow[] }>(
    `/catalog/local-models${queryString({ model_kind: modelKind })}`
  );
  return (payload.data.models ?? []).map((m) => ({
    id: m.id,
    provider_id: m.provider_id,
    display_name: m.display_name,
    model_kind: m.model_kind,
    hosting: m.hosting,
    model_class: m.backend,
    context_window: m.context_window,
    modalities: m.modalities,
    features: m.features,
    notes: m.description,
    pricing: null,
    source: 'local',
    free: m.free,
    downloaded: m.downloaded,
    size_label: m.size_label,
    languages: m.languages,
    manage_hint: m.manage_hint
  }));
}

export async function listActiveProviders(): Promise<ApiResponse<ActiveProviderRow[]>> {
  return apiRequest<ActiveProviderRow[]>('/providers');
}

export async function listAddableProviders(): Promise<ApiResponse<AddableProviderRow[]>> {
  return apiRequest<AddableProviderRow[]>('/providers/addable');
}

export async function addProviderApiKey(providerId: string, apiKey: string) {
  return apiRequest<null>('/providers', {
    method: 'POST',
    body: { provider_id: providerId, api_key: apiKey }
  });
}

export async function scanProviderEnvironment(): Promise<ApiResponse<number>> {
  return apiRequest<number>('/providers/scan-env', { method: 'POST' });
}

export async function removeProvider(providerId: string): Promise<ApiResponse<boolean>> {
  return apiRequest<boolean>(`/providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE'
  });
}
