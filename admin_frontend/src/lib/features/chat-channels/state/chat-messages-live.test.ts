import { describe, expect, it } from 'vitest';
import type { ChatHistoryMessage } from '$lib/api/chat-channels';
import { BACKOFF_STEPS_MS, POLL_INTERVAL_MS } from './chat-channels-poll-config';
import {
  agentVoiceGeneratingId,
  incomingHasAgentReply,
  incomingResolvesVoicePending,
  messageHasAudio,
  messageHasText,
  optimisticIsSuperseded,
  pollIntervalForStreak
} from './chat-messages-live';

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

const audioContent = { content_type: 'audio' as const, body: 'message_attachment:a:0' };
const textContent = { content_type: 'text' as const, body: 'hi there' };

describe('pollIntervalForStreak', () => {
  it('uses the base interval when there is no error streak', () => {
    expect(pollIntervalForStreak(0)).toBe(POLL_INTERVAL_MS);
    expect(pollIntervalForStreak(-3)).toBe(POLL_INTERVAL_MS);
  });

  it('escalates through the backoff steps with the streak', () => {
    expect(pollIntervalForStreak(1)).toBe(BACKOFF_STEPS_MS[0]);
    expect(pollIntervalForStreak(2)).toBe(BACKOFF_STEPS_MS[1]);
    expect(pollIntervalForStreak(3)).toBe(BACKOFF_STEPS_MS[2]);
    expect(pollIntervalForStreak(4)).toBe(BACKOFF_STEPS_MS[3]);
  });

  it('clamps to the last step beyond the configured streak length', () => {
    expect(pollIntervalForStreak(99)).toBe(BACKOFF_STEPS_MS[BACKOFF_STEPS_MS.length - 1]);
  });
});

describe('message content predicates', () => {
  it('detects audio content', () => {
    expect(messageHasAudio(message({ content: [audioContent] }))).toBe(true);
    expect(messageHasAudio(message({ content: [textContent] }))).toBe(false);
  });

  it('treats whitespace-only text as no text', () => {
    expect(messageHasText(message({ content: [textContent] }))).toBe(true);
    expect(messageHasText(message({ content: [{ content_type: 'text', body: '   ' }] }))).toBe(
      false
    );
    expect(messageHasText(message({ content: [audioContent] }))).toBe(false);
  });
});

describe('incomingHasAgentReply', () => {
  it('is true only when a non-user row is present', () => {
    expect(incomingHasAgentReply([message({ sender_type: 'user' })])).toBe(false);
    expect(
      incomingHasAgentReply([message({ sender_type: 'user' }), message({ sender_type: 'assistant' })])
    ).toBe(true);
  });
});

describe('incomingResolvesVoicePending', () => {
  const since = '2026-05-11T00:00:00.000Z';

  it('is false when nothing is pending', () => {
    expect(incomingResolvesVoicePending([message({ content: [audioContent] })], null)).toBe(false);
  });

  it('requires an agent audio message at or after the pending timestamp', () => {
    const agentAudio = message({
      sender_type: 'assistant',
      created_at: '2026-05-11T00:00:01.000Z',
      content: [audioContent]
    });
    expect(incomingResolvesVoicePending([agentAudio], since)).toBe(true);
  });

  it('ignores agent audio that predates the pending timestamp', () => {
    const stale = message({
      sender_type: 'assistant',
      created_at: '2026-05-10T23:59:59.000Z',
      content: [audioContent]
    });
    expect(incomingResolvesVoicePending([stale], since)).toBe(false);
  });

  it('ignores user audio and text-only agent replies', () => {
    const userAudio = message({ sender_type: 'user', content: [audioContent] });
    const agentText = message({ sender_type: 'assistant', content: [textContent] });
    expect(incomingResolvesVoicePending([userAudio, agentText], since)).toBe(false);
  });
});

describe('agentVoiceGeneratingId', () => {
  const since = '2026-05-11T00:00:00.000Z';

  it('returns null when nothing is pending', () => {
    expect(agentVoiceGeneratingId([message({ content: [textContent] })], null)).toBeNull();
  });

  it('returns the latest text-only agent message awaiting audio', () => {
    const older = message({
      id: 'a',
      sender_type: 'assistant',
      created_at: '2026-05-11T00:00:01.000Z',
      content: [textContent]
    });
    const newer = message({
      id: 'b',
      sender_type: 'assistant',
      created_at: '2026-05-11T00:00:02.000Z',
      content: [textContent]
    });
    expect(agentVoiceGeneratingId([older, newer], since)).toBe('b');
  });

  it('skips agent messages that already have audio', () => {
    const withAudio = message({
      id: 'done',
      sender_type: 'assistant',
      created_at: '2026-05-11T00:00:02.000Z',
      content: [textContent, audioContent]
    });
    expect(agentVoiceGeneratingId([withAudio], since)).toBeNull();
  });
});

describe('optimisticIsSuperseded', () => {
  it('is true when a persisted row shares the optimistic external id', () => {
    const persisted = message({ id: 'echo', message_pk: 12 });
    const optimistic = message({ id: 'echo', message_pk: -1 });
    expect(optimisticIsSuperseded([persisted], optimistic)).toBe(true);
  });

  it('is false for a not-yet-persisted optimistic row', () => {
    const optimistic = message({ id: 'echo', message_pk: -1 });
    expect(optimisticIsSuperseded([], optimistic)).toBe(false);
  });

  it('is false for a positive-pk (already persisted) candidate', () => {
    const persisted = message({ id: 'echo', message_pk: 5 });
    expect(optimisticIsSuperseded([persisted], message({ id: 'echo', message_pk: 6 }))).toBe(false);
  });
});
