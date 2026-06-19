import { describe, expect, it } from 'vitest';
import type { ChatHistoryMessage } from '$lib/api/chat-channels';
import {
  agentCostLabel,
  agentElapsedLabel,
  agentMetadataByReplyId,
  agentTokensShouldAnimate,
  formatTokenCount,
  hasVisibleAgentTelemetry,
  resolveAgentMetadata,
  shouldShowAgentTelemetry,
  telemetryBreakdownTitle,
  usageBreakdownTitle
} from './agent-message-meta';

function chatMessage(overrides: Partial<ChatHistoryMessage>): ChatHistoryMessage {
  return {
    id: 'm-1',
    message_pk: 1,
    channel_id: 1,
    sender_type: 'user',
    sender_id: 'admin',
    created_at: '2026-05-13T00:00:00.000Z',
    content: [{ content_type: 'text', body: 'hello' }],
    ...overrides
  };
}

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
      [
        'Cached: 25',
        'Input: 100',
        'Total Input: 125',
        'Reasoning: 7',
        'Output: 35',
        'Total Output: 42'
      ].join('\n')
    );
  });

  it('formats compact cost labels and telemetry tooltip lines', () => {
    const agent = {
      cost: {
        currency: 'USD',
        estimated_total: 0.00003675,
        pricing_available: true
      }
    };

    expect(agentCostLabel(agent)).toBe('$0.000037');
    expect(telemetryBreakdownTitle({ output_tokens: 6 })).toBe(
      ['Cached: 0', 'Input: 0', 'Total Input: 0', 'Reasoning: 0', 'Output: 6', 'Total Output: 6'].join(
        '\n'
      )
    );
  });

  it('formats agent elapsed duration labels', () => {
    expect(agentElapsedLabel({ elapsed_ms: 210 })).toBe('0.21s');
    expect(agentElapsedLabel({ elapsed_ms: 3200 })).toBe('3.2s');
    expect(agentElapsedLabel({ elapsed_ms: 92_000 })).toBe('1:32m');
    expect(agentElapsedLabel({ elapsed_ms: undefined })).toBe('');
  });

  it('does not show a cost label when pricing is unavailable', () => {
    const agent = {
      cost: {
        currency: 'USD',
        estimated_total: 0,
        pricing_available: false,
        reason: 'pricing_missing'
      }
    };

    expect(agentCostLabel(agent)).toBe('');
    expect(telemetryBreakdownTitle(undefined)).toBe('');
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

  it('indexes inbound agent metadata by reply id when only elapsed time is available', () => {
    const messages: ChatHistoryMessage[] = [
      {
        id: 'inbound-1',
        message_pk: 1,
        channel_id: 1,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: '2026-05-13T00:00:00.000Z',
        content: [{ content_type: 'text', body: 'hello' }],
        metadata: { agent: { reply_id: 'reply-1', elapsed_ms: 210 } }
      }
    ];

    expect(agentMetadataByReplyId(messages).get('reply-1')?.elapsed_ms).toBe(210);
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

  it('animates token count only while agent status is processing', () => {
    expect(agentTokensShouldAnimate({ status: 'processing' })).toBe(true);
    expect(agentTokensShouldAnimate({ status: 'completed' })).toBe(false);
    expect(agentTokensShouldAnimate({ status: 'failed' })).toBe(false);
    expect(agentTokensShouldAnimate({ status: undefined })).toBe(false);
    expect(agentTokensShouldAnimate(null)).toBe(false);
  });
});

describe('hasVisibleAgentTelemetry', () => {
  it('is false for null or empty metadata', () => {
    expect(hasVisibleAgentTelemetry(null)).toBe(false);
    expect(hasVisibleAgentTelemetry({})).toBe(false);
    expect(hasVisibleAgentTelemetry({ usage_total: { output_tokens: 0 } })).toBe(false);
  });

  it('is true when tokens, cost, or elapsed are present', () => {
    expect(hasVisibleAgentTelemetry({ usage_total: { output_tokens: 5 } })).toBe(true);
    expect(hasVisibleAgentTelemetry({ elapsed_ms: 200 })).toBe(true);
    expect(
      hasVisibleAgentTelemetry({ cost: { currency: 'USD', estimated_total: 0.01, pricing_available: true } })
    ).toBe(true);
  });
});

describe('resolveAgentMetadata', () => {
  it('returns the message own metadata when present', () => {
    const msg = chatMessage({ metadata: { agent: { reply_id: 'r', usage_total: { output_tokens: 3 } } } });
    const resolved = resolveAgentMetadata(msg, true, new Map());
    expect(resolved?.usage_total?.output_tokens).toBe(3);
  });

  it('falls back to inbound-by-reply-id only for agent (non-user) messages', () => {
    const inbound = new Map([['agent-msg', { usage_total: { output_tokens: 9 } }]]);
    const agentMsg = chatMessage({ id: 'agent-msg', sender_type: 'assistant', metadata: undefined });
    expect(resolveAgentMetadata(agentMsg, false, inbound)?.usage_total?.output_tokens).toBe(9);

    const userMsg = chatMessage({ id: 'agent-msg', sender_type: 'user', metadata: undefined });
    expect(resolveAgentMetadata(userMsg, true, inbound)).toBeNull();
  });
});

describe('shouldShowAgentTelemetry', () => {
  it('always shows for an agent reply with visible telemetry', () => {
    const agent = { usage_total: { output_tokens: 5 } };
    const msg = chatMessage({ id: 'a', sender_type: 'assistant' });
    expect(shouldShowAgentTelemetry(msg, agent, false, [msg])).toBe(true);
  });

  it('hides on the user message when the agent reply already surfaces the same reply_id', () => {
    const userMsg = chatMessage({ id: 'u', sender_type: 'user' });
    const agentReply = chatMessage({
      id: 'reply-1',
      sender_type: 'assistant',
      metadata: { agent: { usage_total: { output_tokens: 8 } } }
    });
    const agent = { reply_id: 'reply-1', usage_total: { output_tokens: 8 } };
    expect(shouldShowAgentTelemetry(userMsg, agent, true, [userMsg, agentReply])).toBe(false);
  });

  it('shows on the user message when no agent reply carries the telemetry', () => {
    const userMsg = chatMessage({ id: 'u', sender_type: 'user' });
    const agent = { reply_id: 'reply-1', usage_total: { output_tokens: 8 } };
    expect(shouldShowAgentTelemetry(userMsg, agent, true, [userMsg])).toBe(true);
  });

  it('is false without visible telemetry', () => {
    const msg = chatMessage({ id: 'a', sender_type: 'assistant' });
    expect(shouldShowAgentTelemetry(msg, null, false, [msg])).toBe(false);
    expect(shouldShowAgentTelemetry(msg, { usage_total: { output_tokens: 0 } }, false, [msg])).toBe(false);
  });
});
