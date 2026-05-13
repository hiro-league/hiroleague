import type { ChatHistoryMessage } from '$lib/api/chat-channels';

export type ChatTailCursor = {
  created_at: string;
  external_id: string;
};

export function sortChatHistoryMessages(messages: ChatHistoryMessage[]): ChatHistoryMessage[] {
  return [...messages].sort((a, b) => {
    const byCreatedAt = a.created_at.localeCompare(b.created_at);
    if (byCreatedAt !== 0) return byCreatedAt;
    return a.id.localeCompare(b.id);
  });
}

function contentItemsEqual(
  a: ChatHistoryMessage['content'][number],
  b: ChatHistoryMessage['content'][number]
): boolean {
  return (
    a.content_type === b.content_type &&
    a.body === b.body &&
    JSON.stringify(a.metadata ?? {}) === JSON.stringify(b.metadata ?? {})
  );
}

export function chatHistoryMessagesEqual(
  a: ChatHistoryMessage,
  b: ChatHistoryMessage
): boolean {
  return (
    a.id === b.id &&
    a.message_pk === b.message_pk &&
    a.channel_id === b.channel_id &&
    a.sender_type === b.sender_type &&
    a.sender_id === b.sender_id &&
    a.created_at === b.created_at &&
    JSON.stringify(a.metadata ?? {}) === JSON.stringify(b.metadata ?? {}) &&
    a.content.length === b.content.length &&
    a.content.every((item, index) => contentItemsEqual(item, b.content[index]!))
  );
}

export function mergeChatHistoryMessages(
  current: ChatHistoryMessage[],
  incoming: ChatHistoryMessage[]
): ChatHistoryMessage[] {
  if (incoming.length === 0) return current;
  const byPk = new Map<number, ChatHistoryMessage>();
  const pkByExternalId = new Map<string, number>();
  for (const message of current) {
    byPk.set(message.message_pk, message);
    pkByExternalId.set(message.id, message.message_pk);
  }
  for (const message of incoming) {
    const previousPk = pkByExternalId.get(message.id);
    if (previousPk !== undefined && previousPk !== message.message_pk) {
      byPk.delete(previousPk);
    }
    const existing = byPk.get(message.message_pk);
    byPk.set(
      message.message_pk,
      existing && chatHistoryMessagesEqual(existing, message) ? existing : message
    );
    pkByExternalId.set(message.id, message.message_pk);
  }
  return sortChatHistoryMessages([...byPk.values()]);
}

export function cursorFromMessages(messages: ChatHistoryMessage[]): ChatTailCursor | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!message || message.message_pk < 0) continue;
    return { created_at: message.created_at, external_id: message.id };
  }
  return null;
}

export function recentMessagePks(messages: ChatHistoryMessage[], count: number): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (let i = messages.length - 1; i >= 0 && out.length < count; i--) {
    const pk = messages[i]?.message_pk;
    if (typeof pk !== 'number' || pk < 1 || seen.has(pk)) continue;
    seen.add(pk);
    out.push(pk);
  }
  return out.reverse();
}
