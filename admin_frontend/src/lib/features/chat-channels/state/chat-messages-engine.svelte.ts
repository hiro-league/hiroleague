import { browser } from '$app/environment';
import { untrack } from 'svelte';
import { listChatMessages, type ChatHistoryMessage } from '$lib/api/chat-channels';
import {
  cursorFromMessages,
  mergeChatHistoryMessages,
  recentMessagePks,
  sortChatHistoryMessages,
  type ChatTailCursor
} from '$lib/features/chat-channels/state/chat-channel-message-merge';
import {
  LIVE_UPDATES_PAUSED_AFTER_FAILURES,
  RECENT_RESYNC_K,
  TAIL_LIMIT
} from '$lib/features/chat-channels/state/chat-channels-poll-config';
import {
  agentVoiceGeneratingId,
  incomingHasAgentReply,
  incomingResolvesVoicePending,
  optimisticIsSuperseded,
  pollIntervalForStreak
} from '$lib/features/chat-channels/state/chat-messages-live';

export type ChatMessagesEngine = ReturnType<typeof createChatMessagesEngine>;

type ChatMessagesEngineOptions = {
  /** Current selected channel id (owned by the parent controller). */
  getSelectedChannelId: () => string | null;
};

/**
 * Live-conversation engine: the message list plus its polling/backoff loop, tail
 * cursor, optimistic reconciliation, and agent typing/voice-pending indicators.
 *
 * Reactive (`$state`/`$derived`/`$effect`), so it must be created inside a
 * long-lived component's reactive context — the chat controller does this from
 * `AdminShell`. The selected channel stays owned by the controller and is read
 * back through `getSelectedChannelId`; the engine is leased on/off screen via
 * `setPageMessagesActive` / `setOverlayActive`.
 */
export function createChatMessagesEngine(opts: ChatMessagesEngineOptions) {
  const { getSelectedChannelId } = opts;

  let messages = $state<ChatHistoryMessage[]>([]);
  let messagesLoading = $state(false);
  let messagesError = $state<string | null>(null);
  let tailCursor = $state<ChatTailCursor | null>(null);
  let syncing = $state(false);
  let pollErrorStreak = $state(0);
  let agentTyping = $state(false);
  let agentVoicePendingSince = $state<string | null>(null);

  let documentVisible = $state(true);
  let messagesSectionMounted = $state(false);
  // Polling is leased by whichever surface is on screen (page Messages tab and/or
  // global overlay); eligibility is OR-ed so a persisted tab pref does not keep
  // polling alive in the background once you navigate away.
  let pageMessagesActive = $state(false);
  let overlayActive = $state(false);

  let pollTimer: number | null = null;
  let pollTickInFlight = false;
  let optimisticMessagePk = -1;

  const liveUpdatesEligible = $derived(
    (pageMessagesActive || overlayActive) &&
      getSelectedChannelId() !== null &&
      documentVisible &&
      messagesSectionMounted
  );

  const liveUpdatesPaused = $derived(pollErrorStreak >= LIVE_UPDATES_PAUSED_AFTER_FAILURES);

  const agentVoiceGeneratingMessageId = $derived.by(() =>
    agentVoiceGeneratingId(messages, agentVoicePendingSince)
  );

  $effect(() => {
    if (!browser) return;
    if (liveUpdatesEligible) {
      untrack(startPolling);
      return () => untrack(stopPolling);
    }
    untrack(stopPolling);
  });

  function currentPollIntervalMs() {
    return pollIntervalForStreak(pollErrorStreak);
  }

  function startPolling() {
    if (!browser || pollTimer !== null) return;
    void pollMessagesOnce();
    pollTimer = window.setInterval(() => {
      void pollMessagesOnce();
    }, currentPollIntervalMs());
  }

  function stopPolling() {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    syncing = false;
  }

  function restartPollingTimer() {
    if (!browser || !liveUpdatesEligible) return;
    stopPolling();
    pollTimer = window.setInterval(() => {
      void pollMessagesOnce();
    }, currentPollIntervalMs());
  }

  function resetPollErrors() {
    const hadBackoff = pollErrorStreak > 0;
    pollErrorStreak = 0;
    if (hadBackoff) restartPollingTimer();
  }

  function updateTailCursor() {
    tailCursor = cursorFromMessages(messages);
  }

  function applyIncoming(incoming: ChatHistoryMessage[]) {
    if (agentTyping && incomingHasAgentReply(incoming)) {
      agentTyping = false;
    }
    if (incomingResolvesVoicePending(incoming, agentVoicePendingSince)) {
      agentVoicePendingSince = null;
    }
    messages = mergeChatHistoryMessages(messages, incoming);
    updateTailCursor();
  }

  async function pollMessagesOnce() {
    if (pollTickInFlight || !liveUpdatesEligible || messagesLoading) return;
    const rawChannelId = getSelectedChannelId();
    const channelId = rawChannelId ? Number(rawChannelId) : NaN;
    if (!Number.isFinite(channelId)) return;

    if (tailCursor === null) {
      updateTailCursor();
      if (tailCursor === null) {
        if (!messages.some((message) => message.message_pk < 0)) return;
        pollTickInFlight = true;
        syncing = true;
        try {
          const payload = await listChatMessages(channelId);
          if (getSelectedChannelId() !== rawChannelId || !liveUpdatesEligible) return;
          applyIncoming(payload.data);
          resetPollErrors();
        } catch {
          pollErrorStreak += 1;
          restartPollingTimer();
        } finally {
          if (getSelectedChannelId() === rawChannelId) {
            syncing = false;
          }
          pollTickInFlight = false;
        }
        return;
      }
    }

    pollTickInFlight = true;
    syncing = true;
    try {
      const cursor = tailCursor;
      const tailPayload = await listChatMessages(channelId, {
        after: cursor.created_at,
        afterId: cursor.external_id,
        limit: TAIL_LIMIT
      });
      if (getSelectedChannelId() !== rawChannelId || !liveUpdatesEligible) return;
      if (tailPayload.data.length > 0) {
        applyIncoming(tailPayload.data);
      }

      if (!liveUpdatesEligible) return;
      const messagePks = recentMessagePks(messages, RECENT_RESYNC_K);
      if (messagePks.length > 0) {
        const resyncPayload = await listChatMessages(channelId, { messagePks });
        if (getSelectedChannelId() !== rawChannelId || !liveUpdatesEligible) return;
        if (resyncPayload.data.length > 0) {
          if (incomingResolvesVoicePending(resyncPayload.data, agentVoicePendingSince)) {
            agentVoicePendingSince = null;
          }
          messages = mergeChatHistoryMessages(messages, resyncPayload.data);
          updateTailCursor();
        }
      }
      resetPollErrors();
    } catch {
      pollErrorStreak += 1;
      restartPollingTimer();
    } finally {
      if (getSelectedChannelId() === rawChannelId) {
        syncing = false;
      }
      pollTickInFlight = false;
    }
  }

  function handleVisibilityChange() {
    documentVisible = document.visibilityState === 'visible';
  }

  /** Reset the conversation view (channel switch): drop messages/cursor/agent indicators. */
  function resetConversation() {
    messages = [];
    tailCursor = null;
    agentTyping = false;
    agentVoicePendingSince = null;
  }

  /** Reset + clear any load error (no channel selected / nothing to show). */
  function clearConversation() {
    resetConversation();
    messagesError = null;
  }

  /** Full (re)load of a channel's history — replaces the message list and tail cursor. */
  async function loadConversation(channelId: number) {
    messagesLoading = true;
    messagesError = null;
    messages = [];
    tailCursor = null;
    try {
      const payload = await listChatMessages(channelId);
      if (payload.data.at(-1)?.sender_type !== 'user') {
        agentTyping = false;
      }
      if (incomingResolvesVoicePending(payload.data, agentVoicePendingSince)) {
        agentVoicePendingSince = null;
      }
      messages = sortChatHistoryMessages(payload.data);
      updateTailCursor();
      resetPollErrors();
    } catch (err) {
      messagesError = err instanceof Error ? err.message : 'Failed to load messages.';
    } finally {
      messagesLoading = false;
    }
  }

  /** Next monotonically-decreasing placeholder pk for an optimistic (unsent) row. */
  function nextOptimisticPk(): number {
    return optimisticMessagePk--;
  }

  function addOptimisticMessage(message: ChatHistoryMessage) {
    if (optimisticIsSuperseded(messages, message)) return;
    messages = mergeChatHistoryMessages(messages, [message]);
  }

  /** After a send: show the typing indicator and (when voice was requested) arm voice-pending. */
  function markAgentReplyPending(sentAt: string, requestVoiceReply: boolean) {
    agentTyping = true;
    agentVoicePendingSince = requestVoiceReply ? sentAt : null;
  }

  /** One-time runtime boot: document-visibility tracking + mark the section mounted. */
  function startRuntime() {
    messagesSectionMounted = true;
    if (browser) {
      documentVisible = document.visibilityState === 'visible';
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }
  }

  function dispose() {
    messagesSectionMounted = false;
    if (browser) {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    }
    stopPolling();
  }

  function setPageMessagesActive(active: boolean) {
    pageMessagesActive = active;
  }

  function setOverlayActive(active: boolean) {
    overlayActive = active;
  }

  return {
    startRuntime,
    dispose,
    setPageMessagesActive,
    setOverlayActive,

    loadConversation,
    resetConversation,
    clearConversation,
    resetPollErrors,

    nextOptimisticPk,
    addOptimisticMessage,
    markAgentReplyPending,

    get messages(): ChatHistoryMessage[] {
      return messages;
    },
    get messagesLoading(): boolean {
      return messagesLoading;
    },
    get messagesError(): string | null {
      return messagesError;
    },
    get syncing(): boolean {
      return syncing;
    },
    get agentTyping(): boolean {
      return agentTyping;
    },
    get agentVoiceGeneratingMessageId(): string | null {
      return agentVoiceGeneratingMessageId;
    },
    get liveUpdatesPaused(): boolean {
      return liveUpdatesPaused;
    }
  };
}
