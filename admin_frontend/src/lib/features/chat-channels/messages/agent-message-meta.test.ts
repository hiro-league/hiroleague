import { describe, expect, it } from 'vitest';
import type { ChatHistoryMessage } from '$lib/api/chat-channels';
import { agentMetadataByReplyId, formatTokenCount, usageBreakdownTitle } from './agent-message-meta';

describe('agent message metadata display', () => {
  it('formats output token counts using the admin compact thresholds', () => {
    expect(formatTokenCount(999)).toBe('999');
    expect(formatTokenCount(9_999)).toBe('9,999');
    expect(formatTokenCount(10_000)).toBe('10k');
    expect(formatTokenCount(10_500)).toBe('10.5k');
    expect(formatTokenCount(99_900)).toBe('99.9k');
    expect(formatTokenCount(100_000)).toBe('100k');
    expect(formatTokenCount(1_000_000)).toBe('1M');
    expect(formatTokenCount(1_234_000)).toBe('1.234M');
  });

  it('builds the multi-line usage tooltip from usage totals', () => {
    expect(
      usageBreakdownTitle({
        output_tokens: 42,
        input_tokens: 100,
        total_tokens: 142,
        cached_input_tokens: 25,
        reasoning_tokens: 7
      })
    ).toBe(
      ['Output: 42 tokens', 'Input: 100 tokens', 'Total: 142 tokens', 'Cached input: 25 tokens', 'Reasoning: 7 tokens'].join(
        '\n'
      )
    );
  });

  it('indexes inbound agent metadata by reply id', () => {
    const messages: ChatHistoryMessage[] = [
      {
        id: 'inbound-1',
        message_pk: 1,
        channel_id: 1,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: '2026-05-13T00:00:00.000Z',
        content: [{ content_type: 'text', body: 'hello' }],
        metadata: {
          agent: {
            reply_id: 'reply-1',
            usage_total: { output_tokens: 12 }
          }
        }
      }
    ];

    expect(agentMetadataByReplyId(messages).get('reply-1')?.usage_total?.output_tokens).toBe(12);
  });

  it('does not index inbound agent metadata without output tokens', () => {
    const messages: ChatHistoryMessage[] = [
      {
        id: 'inbound-1',
        message_pk: 1,
        channel_id: 1,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: '2026-05-13T00:00:00.000Z',
        content: [{ content_type: 'text', body: 'hello' }],
        metadata: { agent: { reply_id: 'reply-1', usage_total: { output_tokens: 0 } } }
      }
    ];

    expect(agentMetadataByReplyId(messages).has('reply-1')).toBe(false);
  });
});
