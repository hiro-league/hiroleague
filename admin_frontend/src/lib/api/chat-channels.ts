import { apiRequest } from './client';

export type ChatChannelRow = {
  id: number;
  name: string;
  type: string;
  character_id: string;
  user_id: number;
  created_at: string;
  last_message_at: string | null;
};

export type ChatMessageRow = {
  id: number;
  external_id: string;
  channel_id: number;
  user_id: number | null;
  sender_type: string;
  sender_id: string;
  content_type: string;
  body: string;
  media_path: string | null;
  metadata: unknown;
  created_at: string;
};

export type ChatChannelPayload = {
  name: string;
  user_id: number;
  character_id: string;
  channel_type: string;
};

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

export async function listChatMessages(channelId: number) {
  return apiRequest<ChatMessageRow[]>(`/chat-channels/${channelId}/messages`);
}
