import { apiRequest, type ApiResponse } from './client';

export type AdminConfig = {
  hiro_env: string;
  docs_base_url: string;
};

export const DEFAULT_ADMIN_CONFIG: AdminConfig = {
  hiro_env: 'prod',
  docs_base_url: 'https://docs.hiroleague.com'
};

export async function getAdminConfig(): Promise<ApiResponse<AdminConfig>> {
  return apiRequest<AdminConfig>('/config');
}

export function docsUrl(config: AdminConfig, path: string): string {
  const base = config.docs_base_url.replace(/\/+$/, '');
  const normalizedPath = path.replace(/^\/+/, '');
  return normalizedPath ? `${base}/${normalizedPath}` : base;
}
