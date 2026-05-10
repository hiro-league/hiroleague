import { base } from '$app/paths';
import { PREF_KEYS } from '$lib/preferences/keys';
import { apiRequest } from './client';

export type ChatChannelRow = {
  id: number;
  name: string;
  type: string;
  character_id: string;
  user_id: number;
  description?: string;
  created_at: string;
  last_message_at: string | null;
  last_deleted: number;
  character?: { id: string; name: string };
  capabilities?: unknown;
  is_lowest_id_channel?: boolean;
  photo_data_url?: string | null;
  thumbnail_mtime_ns?: number;
};

/** One item in ``messages.history`` / admin list (text, audio, …). */
export type ChatMessageContentItem = {
  content_type: string;
  body: string;
  metadata?: Record<string, unknown>;
};

/** Normalized history row from ``_sync_history`` (admin chat Messages tab). */
export type ChatHistoryMessage = {
  /** Protocol / external message id (UUID hex, etc.). */
  id: string;
  message_pk: number;
  channel_id: number;
  sender_type: string;
  sender_id: string;
  created_at: string;
  content: ChatMessageContentItem[];
};

export type ChatChannelPayload = {
  name: string;
  character_id: string;
  description: string;
};

const apiBase = `${base}/api`;

export function historyMessageText(m: ChatHistoryMessage): string {
  return m.content
    .filter((c) => c.content_type === 'text')
    .map((c) => c.body)
    .filter(Boolean)
    .join('\n')
    .trim();
}

export function historyMessageFirstAudio(m: ChatHistoryMessage): ChatMessageContentItem | null {
  return m.content.find((c) => c.content_type === 'audio') ?? null;
}

/** Parse slot index from ``message_attachment:<id>:<slot>`` body. */
export function parseMessageAttachmentSlot(body: string): number | null {
  if (!body.startsWith('message_attachment:')) return null;
  const rest = body.slice('message_attachment:'.length);
  const idx = rest.lastIndexOf(':');
  if (idx < 0) return null;
  const n = Number.parseInt(rest.slice(idx + 1), 10);
  return Number.isNaN(n) ? null : n;
}

export async function listChatChannels() {
  return apiRequest<ChatChannelRow[]>('/chat-channels');
}

export async function createChatChannel(payload: ChatChannelPayload) {
  return apiRequest<ChatChannelRow>('/chat-channels', { method: 'POST', body: payload });
}

export async function updateChatChannel(channelId: number, payload: ChatChannelPayload) {
  return apiRequest<ChatChannelRow>(`/chat-channels/${channelId}`, {
    method: 'PATCH',
    body: payload
  });
}

export async function deleteChatChannel(channelId: number) {
  return apiRequest<number>(`/chat-channels/${channelId}`, { method: 'DELETE' });
}

export async function uploadChatChannelPhoto(channelId: number, dataUrl: string) {
  return apiRequest<null>(`/chat-channels/${channelId}/photo`, {
    method: 'POST',
    body: { data_url: dataUrl }
  });
}

export async function listChatMessages(channelId: number) {
  return apiRequest<ChatHistoryMessage[]>(`/chat-channels/${channelId}/messages`);
}

/** Proxy to workspace Hiro POST /invoke message_send — server must be running. */
export async function sendChatMessage(
  channelId: number,
  body: {
    text?: string;
    audio_base64?: string;
    audio_mime_type?: string;
    audio_duration_ms?: number;
    request_voice_reply?: boolean;
  }
) {
  return apiRequest<{ message_id: string; channel_id: number }>(
    `/chat-channels/${channelId}/messages/send`,
    { method: 'POST', body }
  );
}

/** Bulk-delete conversation messages — channel stays; bumps ``last_deleted`` on devices. */
export async function clearChatMessages(channelId: number) {
  return apiRequest<{ channel_id: number; last_deleted: number }>(
    `/chat-channels/${channelId}/messages/clear`,
    { method: 'POST' }
  );
}

/**
 * Load attachment bytes for `<audio>` — uses ``X-Hiro-Workspace`` (plain media
 * ``<audio src>`` cannot).
 */
export async function fetchChatMessageAttachmentBlob(
  channelId: number,
  externalMessageId: string,
  slot: number
): Promise<Blob> {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const headers = new Headers();
  if (selectedWorkspace) {
    headers.set('x-hiro-workspace', selectedWorkspace);
  }
  const enc = encodeURIComponent(externalMessageId);
  const response = await fetch(
    `${apiBase}/chat-channels/${channelId}/messages/by-external/${enc}/attachments/${slot}/media`,
    { headers }
  );
  if (!response.ok) {
    const err = await response.text().catch(() => '');
    throw new Error(err || `HTTP ${response.status}`);
  }
  return response.blob();
}
