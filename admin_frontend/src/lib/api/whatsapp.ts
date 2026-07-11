import { apiRequest, type ApiResponse } from './client';

export type WhatsAppStatus = {
  state: string;
  account: string;
  has_qr: boolean;
  enabled: boolean;
  state_at: string | null;
  /** Diagnostic detail for terminal states (reason/code/expire/message). */
  detail?: Record<string, unknown>;
};

export type WhatsAppQr = { qr_svg: string; qr_at: string | null };

export type WhatsAppConfig = Record<string, unknown>;

export async function getWhatsAppStatus(): Promise<ApiResponse<WhatsAppStatus>> {
  return apiRequest<WhatsAppStatus>('/whatsapp/status');
}

export async function getWhatsAppQr(): Promise<ApiResponse<WhatsAppQr>> {
  return apiRequest<WhatsAppQr>('/whatsapp/qr');
}

export async function getWhatsAppConfig(): Promise<ApiResponse<{ config: WhatsAppConfig }>> {
  return apiRequest<{ config: WhatsAppConfig }>('/whatsapp/config');
}

/** Set a single config key (value: any JSON; null unsets). Server applies on restart. */
export async function setWhatsAppConfig(
  key: string,
  value: unknown
): Promise<ApiResponse<{ config: WhatsAppConfig }>> {
  return apiRequest<{ config: WhatsAppConfig }>('/whatsapp/config', {
    method: 'POST',
    body: { key, value }
  });
}

/** Live channel lifecycle actions (no server restart). */
export async function enableWhatsApp(): Promise<ApiResponse<{ enabled: boolean }>> {
  return apiRequest<{ enabled: boolean }>('/whatsapp/enable', { method: 'POST' });
}

export async function disableWhatsApp(): Promise<ApiResponse<{ enabled: boolean }>> {
  return apiRequest<{ enabled: boolean }>('/whatsapp/disable', { method: 'POST' });
}

/** Unlink the WhatsApp account; a fresh QR is issued to re-pair. */
export async function logoutWhatsApp(): Promise<ApiResponse<{ requested: boolean }>> {
  return apiRequest<{ requested: boolean }>('/whatsapp/logout', { method: 'POST' });
}

/** Force a re-link using the saved session (no new QR). */
export async function reconnectWhatsApp(): Promise<ApiResponse<{ requested: boolean }>> {
  return apiRequest<{ requested: boolean }>('/whatsapp/reconnect', { method: 'POST' });
}
