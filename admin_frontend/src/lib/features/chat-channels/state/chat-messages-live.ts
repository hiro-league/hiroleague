import type { ChatHistoryMessage } from '$lib/api/chat-channels';
import { BACKOFF_STEPS_MS, POLL_INTERVAL_MS } from './chat-channels-poll-config';

/**
 * Pure decision helpers for the live-message engine — backoff intervals, agent
 * typing/voice resolution, and optimistic-message reconciliation.
 *
 * Kept side-effect-free (no `$state`, no timers, no DOM) so the branchy logic that
 * drives polling is unit-testable; the stateful `chat-messages-engine.svelte.ts`
 * composes these with reactive state.
 */

/** Poll cadence for a given consecutive-error streak: base interval, then escalating backoff steps. */
export function pollIntervalForStreak(
  streak: number,
  baseMs: number = POLL_INTERVAL_MS,
  steps: readonly number[] = BACKOFF_STEPS_MS
): number {
  if (streak <= 0) return baseMs;
  const idx = Math.min(streak - 1, steps.length - 1);
  return steps[idx] ?? baseMs;
}

export function messageHasAudio(message: ChatHistoryMessage): boolean {
  return message.content.some((item) => item.content_type === 'audio');
}

export function messageHasText(message: ChatHistoryMessage): boolean {
  return message.content.some((item) => item.content_type === 'text' && item.body.trim() !== '');
}

/** True once any non-user (agent) row arrives — used to drop the "agent is typing" indicator. */
export function incomingHasAgentReply(incoming: ChatHistoryMessage[]): boolean {
  return incoming.some((message) => message.sender_type !== 'user');
}

/**
 * True when an incoming batch satisfies a pending voice reply: an agent message at
 * or after `since` that actually carries audio. `since` null ⇒ nothing pending.
 */
export function incomingResolvesVoicePending(
  incoming: ChatHistoryMessage[],
  since: string | null
): boolean {
  if (!since) return false;
  return incoming.some(
    (message) =>
      message.sender_type !== 'user' && message.created_at >= since && messageHasAudio(message)
  );
}

/**
 * Id of the agent message currently generating a voice reply: the most recent agent
 * message at/after `since` that has text but no audio yet (so the UI can show a
 * "synthesizing voice" affordance on it). Null when nothing is pending/matches.
 */
export function agentVoiceGeneratingId(
  messages: ChatHistoryMessage[],
  since: string | null
): string | null {
  if (!since) return null;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (
      message &&
      message.sender_type !== 'user' &&
      message.created_at >= since &&
      messageHasText(message) &&
      !messageHasAudio(message)
    ) {
      return message.id;
    }
  }
  return null;
}

/**
 * True when an optimistic (negative-pk) row is already superseded by a persisted
 * copy (same external id, positive pk) — so it should not be re-added on a late echo.
 */
export function optimisticIsSuperseded(
  messages: ChatHistoryMessage[],
  candidate: ChatHistoryMessage
): boolean {
  return (
    candidate.message_pk < 0 &&
    messages.some((existing) => existing.id === candidate.id && existing.message_pk > 0)
  );
}
