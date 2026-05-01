import { apiRequest, type ApiResponse } from './client';

export type AdminConfig = {
  hiro_env: string;
  docs_base_url: string;
  workspace_id: string | null;
  workspace_name: string | null;
  python_version: string;
  hiro_package_version: string;
};

export const DEFAULT_ADMIN_CONFIG: AdminConfig = {
  hiro_env: 'prod',
  docs_base_url: 'https://docs.hiroleague.com',
  workspace_id: null,
  workspace_name: null,
  python_version: 'unknown',
  hiro_package_version: 'unknown'
};

export async function getAdminConfig(): Promise<ApiResponse<AdminConfig>> {
  return apiRequest<AdminConfig>('/config');
}

export function docsUrl(config: AdminConfig, path: string): string {
  const base = config.docs_base_url.replace(/\/+$/, '');
  const normalizedPath = path.replace(/^\/+/, '');
  return normalizedPath ? `${base}/${normalizedPath}` : base;
}
