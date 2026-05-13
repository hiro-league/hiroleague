import { describe, expect, it } from 'vitest';
import type { ChatHistoryMessage } from '$lib/api/chat-channels';
import {
  cursorFromMessages,
  mergeChatHistoryMessages,
  recentMessagePks
} from './chat-channel-message-merge';

function message(overrides: Partial<ChatHistoryMessage>): ChatHistoryMessage {
  return {
    id: 'ext-1',
    message_pk: 1,
    channel_id: 1,
    sender_type: 'user',
    sender_id: 'admin',
    created_at: '2026-05-11T00:00:00.000Z',
    content: [{ content_type: 'text', body: 'hello' }],
    ...overrides
  };
}

describe('chat channel message merge', () => {
  it('preserves the existing object when a resynced row is unchanged', () => {
    const existing = message({
      id: 'audio-id',
      message_pk: 9,
      content: [
        {
          content_type: 'audio',
          body: 'message_attachment:audio-id:0',
          metadata: { duration_ms: 1200, media_type: 'audio/webm' }
        }
      ]
    });
    const incoming = message({
      id: 'audio-id',
      message_pk: 9,
      content: [
        {
          content_type: 'audio',
          body: 'message_attachment:audio-id:0',
          metadata: { duration_ms: 1200, media_type: 'audio/webm' }
        }
      ]
    });

    const merged = mergeChatHistoryMessages([existing], [incoming]);

    expect(merged[0]).toBe(existing);
  });

  it('replaces the existing object when message metadata changes', () => {
    const existing = message({
      metadata: { agent: { status: 'processing', usage_total: { output_tokens: 9 } } }
    });
    const incoming = message({
      metadata: { agent: { status: 'processing', usage_total: { output_tokens: 12 } } }
    });

    const merged = mergeChatHistoryMessages([existing], [incoming]);

    expect(merged[0]).toBe(incoming);
  });

  it('keeps agent usage when PK resync omits output_tokens (admin poll merge)', () => {
    const existing = message({
      id: 'reply-live',
      message_pk: 41,
      sender_type: 'agent',
      metadata: { agent: { usage_total: { output_tokens: 31 }, status: 'completed' } }
    });
    const incoming = message({
      id: 'reply-live',
      message_pk: 41,
      sender_type: 'agent',
      metadata: {}
    });

    const merged = mergeChatHistoryMessages([existing], [incoming]);

    expect(
      (merged[0]?.metadata?.agent as { usage_total?: { output_tokens?: number } })?.usage_total
        ?.output_tokens
    ).toBe(31);
  });

  it('reuses the same row reference when resync strips agent usage but content is unchanged (audio + text)', () => {
    const existing = message({
      id: 'reply-audio',
      message_pk: 41,
      sender_type: 'agent',
      content: [
        { content_type: 'text', body: 'hi' },
        {
          content_type: 'audio',
          body: 'message_attachment:reply-audio:0',
          metadata: { duration_ms: 1000, media_type: 'audio/mpeg' }
        }
      ],
      metadata: { agent: { usage_total: { output_tokens: 31 } } }
    });
    const incoming = message({
      id: 'reply-audio',
      message_pk: 41,
      sender_type: 'agent',
      content: [
        { content_type: 'text', body: 'hi' },
        {
          content_type: 'audio',
          body: 'message_attachment:reply-audio:0',
          metadata: { duration_ms: 1000, media_type: 'audio/mpeg' }
        }
      ],
      metadata: {}
    });

    const merged = mergeChatHistoryMessages([existing], [incoming]);
    expect(merged[0]).toBe(existing);
  });

  it('replaces an optimistic row with the real row when external ids match', () => {
    const optimistic = message({
      id: 'same-external-id',
      message_pk: -1,
      content: [{ content_type: 'text', body: 'optimistic' }]
    });
    const real = message({
      id: 'same-external-id',
      message_pk: 42,
      content: [{ content_type: 'text', body: 'real' }]
    });

    const merged = mergeChatHistoryMessages([optimistic], [real]);

    expect(merged).toHaveLength(1);
    expect(merged[0]?.message_pk).toBe(42);
    expect(merged[0]?.content[0]?.body).toBe('real');
  });

  it('does not use optimistic rows for the tail cursor or recent pk resync', () => {
    const real = message({
      id: 'real-id',
      message_pk: 7,
      created_at: '2026-05-11T00:00:00.000Z'
    });
    const optimistic = message({
      id: 'optimistic-id',
      message_pk: -1,
      created_at: '2026-05-11T00:00:10.000Z'
    });

    expect(cursorFromMessages([real, optimistic])).toEqual({
      created_at: real.created_at,
      external_id: real.id
    });
    expect(recentMessagePks([real, optimistic], 2)).toEqual([7]);
  });

  it('keeps server ordering by created_at then external id', () => {
    const later = message({
      id: 'c',
      message_pk: 2,
      created_at: '2026-05-11T00:00:01.000Z'
    });
    const tieLaterId = message({
      id: 'b',
      message_pk: 3,
      created_at: '2026-05-11T00:00:00.000Z'
    });
    const tieEarlierId = message({
      id: 'a',
      message_pk: 4,
      created_at: '2026-05-11T00:00:00.000Z'
    });

    const merged = mergeChatHistoryMessages([], [later, tieLaterId, tieEarlierId]);

    expect(merged.map((m) => m.id)).toEqual(['a', 'b', 'c']);
    expect(merged.map((m) => m.message_pk)).toEqual([4, 3, 2]);
  });
});
