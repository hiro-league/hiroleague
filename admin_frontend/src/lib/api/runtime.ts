import { apiRequest, type ApiResponse } from './client';

/** Runtime readiness snapshot — see ``admin_svelte/routes/runtime.py``. */
export type RuntimeStatus = {
  ready: boolean;
  main_http_listening: boolean;
  admin_port: number;
  http_port: number;
};

/** GET ``/api/runtime/status`` — TCP probe of the main HiroServer HTTP port. */
export async function getRuntimeStatus(): Promise<ApiResponse<RuntimeStatus>> {
  return apiRequest<RuntimeStatus>('/runtime/status', { timeoutMs: 3000 });
}
