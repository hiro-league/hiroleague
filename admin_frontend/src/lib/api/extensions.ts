import { apiRequest } from './client';

/** A paired extension (HomeHiro first), with its live connection when the server runs here. */
export type ExtensionRow = {
  extension_id: string;
  name: string;
  version: string;
  description: string;
  paired_at: string | null;
  last_seen: string | null;
  connected: boolean;
  connected_at: string | null;
  remote: string | null;
};

/** Where extensions connect: the configured address plus what the running server does. */
export type ExtensionListen = {
  host: string;
  port: number;
  address: string;
  changed: boolean;
  restart_required: boolean;
  note: string;
  /** null when this workspace's server isn't the one running here. */
  listening: boolean | null;
  error: string | null;
  /** The address the running server listens on (differs from `host` until a restart). */
  live_host: string | null;
};

export type ExtensionListData = {
  listen: ExtensionListen;
  extensions: ExtensionRow[];
};

export type ExtensionPairingData = {
  code: string;
  expires_at: string;
  address: string;
};

export type ExtensionAddressData = Omit<ExtensionListen, 'listening' | 'error' | 'live_host'>;

export type ExtensionInfoData = {
  info: { name: string; version: string; description?: string };
  elapsed_ms: number;
};

export async function listExtensions() {
  return apiRequest<ExtensionListData>('/extensions');
}

export async function generateExtensionPairingCode() {
  return apiRequest<ExtensionPairingData>('/extensions/pairing-code', { method: 'POST' });
}

export async function removeExtension(extensionId: string) {
  return apiRequest<string>(`/extensions/${encodeURIComponent(extensionId)}`, { method: 'DELETE' });
}

export async function setExtensionAddress(host: string) {
  return apiRequest<ExtensionAddressData>('/extensions/address', {
    method: 'PUT',
    body: { host }
  });
}

/** The core's test call: ask a connected extension for its name and version. */
export async function askExtensionInfo(extensionId: string) {
  return apiRequest<ExtensionInfoData>(`/extensions/${encodeURIComponent(extensionId)}/info`, {
    method: 'POST'
  });
}
