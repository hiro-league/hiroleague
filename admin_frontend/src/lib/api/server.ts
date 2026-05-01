import { apiRequest, type ApiResponse } from './client';

export type WorkspaceRow = {
  id: string;
  name: string;
  path: string;
  running: boolean;
  pid: number | null;
  ws_connected: boolean;
  last_connected: string | null;
  is_current: boolean;
  is_default: boolean;
  is_configured: boolean;
  http_port: number;
  plugin_port: number;
  admin_port: number;
  port_slot: number;
  gateway_url: string | null;
  autostart_method: string | null;
  stderr_log_path: string;
  stderr_log_exists: boolean;
  stderr_log_size: number;
  stderr_log_mtime: string | null;
  stderr_log_recent: boolean;
};

export type GatewayRow = {
  name: string;
  running: boolean;
  pid: number | null;
  host: string;
  port: number;
  path: string;
  is_default: boolean;
  autostart_method: string | null;
  desktop_connected?: boolean;
  last_auth_error?: string | null;
  stderr_log_path: string;
  stderr_log_exists: boolean;
  stderr_log_size: number;
  stderr_log_mtime: string | null;
  stderr_log_recent: boolean;
};

export type WorkspaceStartResult = {
  name: string;
  already_running: boolean;
  pid: number | null;
};

export type WorkspaceSetupResult = {
  workspace: string;
  desktop_pub: string;
};

export type GatewayStartResult = {
  already_running: boolean;
  pid: number | null;
};

export async function listWorkspaces(): Promise<ApiResponse<WorkspaceRow[]>> {
  return apiRequest<WorkspaceRow[]>('/workspaces');
}

export async function createWorkspace(body: { name: string; path?: string | null }) {
  return apiRequest<string>('/workspaces', { method: 'POST', body });
}

export async function updateWorkspace(
  id: string,
  body: {
    name?: string | null;
    gateway_url?: string | null;
    set_default?: boolean;
    previous_display_name: string;
  }
) {
  return apiRequest<string>(`/workspaces/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body
  });
}

export async function removeWorkspace(id: string, purge: boolean) {
  return apiRequest<string>(`/workspaces/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    body: { purge }
  });
}

export async function startWorkspace(id: string) {
  return apiRequest<WorkspaceStartResult>(`/workspaces/${encodeURIComponent(id)}/start`, {
    method: 'POST'
  });
}

export async function stopWorkspace(id: string) {
  return apiRequest<string>(`/workspaces/${encodeURIComponent(id)}/stop`, { method: 'POST' });
}

export async function restartWorkspace(id: string, admin: boolean) {
  return apiRequest<null>(`/workspaces/${encodeURIComponent(id)}/restart`, {
    method: 'POST',
    body: { admin }
  });
}

export async function setupWorkspace(
  id: string,
  body: {
    gateway_url: string;
    http_port?: number | null;
    skip_autostart: boolean;
    start_server: boolean;
    elevated_task: boolean;
  }
) {
  return apiRequest<WorkspaceSetupResult>(`/workspaces/${encodeURIComponent(id)}/setup`, {
    method: 'POST',
    body
  });
}

export async function getWorkspacePublicKey(id: string) {
  return apiRequest<string>(`/workspaces/${encodeURIComponent(id)}/public-key`);
}

export async function regenerateWorkspaceKey(id: string) {
  return apiRequest<string>(`/workspaces/${encodeURIComponent(id)}/regenerate-key`, {
    method: 'POST'
  });
}

export async function openWorkspaceFolder(path: string) {
  return apiRequest<null>('/workspaces/open-folder', {
    method: 'POST',
    body: { path }
  });
}

export async function openPath(path: string) {
  return apiRequest<null>('/open-path', {
    method: 'POST',
    body: { path }
  });
}

export async function listGateways() {
  return apiRequest<GatewayRow[]>('/gateways');
}

export async function createGateway(body: {
  name: string;
  desktop_public_key: string;
  port: number;
  host: string;
  log_dir?: string;
  make_default: boolean;
  skip_autostart: boolean;
  elevated_task: boolean;
}) {
  return apiRequest<string>('/gateways', { method: 'POST', body });
}

export async function startGateway(name: string, verbose = false) {
  return apiRequest<GatewayStartResult>(`/gateways/${encodeURIComponent(name)}/start`, {
    method: 'POST',
    body: { verbose }
  });
}

export async function stopGateway(name: string) {
  return apiRequest<boolean>(`/gateways/${encodeURIComponent(name)}/stop`, { method: 'POST' });
}

export async function removeGateway(name: string, purge: boolean, elevatedTask = false) {
  return apiRequest<string>(`/gateways/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    body: { purge, elevated_task: elevatedTask }
  });
}
