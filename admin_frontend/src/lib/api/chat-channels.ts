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

export type AgentUsageTotals = {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cached_input_tokens?: number;
  reasoning_tokens?: number;
};

export type AgentToolCall = {
  id?: string;
  name?: string;
  status?: string;
  elapsed_ms?: number;
  /** Single-line JSON (or string) of invocation parameters. */
  args?: string;
  /** Tool return payload (truncated server-side when persisted). */
  result?: string;
  error?: string;
};

export type AgentCostSummary = {
  currency?: string;
  estimated_total?: number;
  pricing_available?: boolean;
  reason?: string;
};

export type AgentMessageMetadata = {
  status?: string;
  current_step?: string | null;
  last_event?: string;
  reply_id?: string;
  elapsed_ms?: number;
  error?: {
    message?: string;
    code?: string;
    node?: string;
  };
  usage_total?: AgentUsageTotals;
  cost?: AgentCostSummary;
  tools?: AgentToolCall[];
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
  metadata?: Record<string, unknown> & { agent?: AgentMessageMetadata };
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

export type ListChatMessagesOptions = {
  after?: string;
  afterId?: string;
  limit?: number;
  messagePks?: number[];
};

export async function listChatMessages(
  channelId: number,
  options: ListChatMessagesOptions = {}
) {
  const params = new URLSearchParams();
  const hasAfter = options.after !== undefined;
  const hasAfterId = options.afterId !== undefined;
  const hasMessagePks = (options.messagePks?.length ?? 0) > 0;
  if (hasMessagePks && (hasAfter || hasAfterId || options.limit !== undefined)) {
    throw new Error('messagePks cannot be combined with cursor options.');
  }
  if (hasAfter !== hasAfterId) {
    throw new Error('after and afterId must be provided together.');
  }
  if (hasAfter && options.limit === undefined) {
    throw new Error('limit is required with after and afterId.');
  }
  if (!hasAfter && !hasMessagePks && options.limit !== undefined) {
    throw new Error('limit is only supported with after and afterId.');
  }

  if (hasAfter && hasAfterId) {
    params.set('after', options.after!);
    params.set('after_id', options.afterId!);
    params.set('limit', String(options.limit));
  }
  if (hasMessagePks) {
    for (const pk of options.messagePks ?? []) {
      params.append('message_pk', String(pk));
    }
  }
  const query = params.toString();
  return apiRequest<ChatHistoryMessage[]>(
    `/chat-channels/${channelId}/messages${query ? `?${query}` : ''}`
  );
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
    use_knowledge?: boolean;
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
