import { apiRequest, type ApiResponse } from './client';

/** Preset voice id for a provider's bundled TTS API (matches catalog.yaml tts_voices). */
export type CatalogTtsVoiceRow = {
  id: string;
  display_name?: string | null;
  description?: string | null;
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
  metadata_updated_at?: string | null;
  notes?: string | null;
};

export type CatalogModelRow = {
  id: string;
  provider_id: string;
  display_name: string;
  model_kind: 'chat' | 'tts' | 'stt' | 'embedding' | 'image_gen' | string;
  model_class?: string | null;
  hosting?: 'cloud' | 'local' | string | null;
  context_window?: number | null;
  modalities?: string[];
  features?: string[];
  tags?: string[];
  pricing?: Record<string, unknown> | null;
  deprecated_since?: string | null;
  replacement_id?: string | null;
  notes?: string | null;
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
