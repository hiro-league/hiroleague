<script lang="ts">
  import { tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import { ArrowDown, MessageCircle, MessagesSquare } from '@lucide/svelte';
  import ChatMessageBubble from '$lib/features/chat-channels/messages/ChatMessageBubble.svelte';
  import ChatComposerOptions from '$lib/features/chat-channels/messages/ChatComposerOptions.svelte';
  import ChatMessageComposer from '$lib/features/chat-channels/messages/ChatMessageComposer.svelte';
  import ChatMessagesToolbar from '$lib/features/chat-channels/messages/ChatMessagesToolbar.svelte';
  import { agentMetadataByReplyId } from '$lib/features/chat-channels/messages/agent-message-meta';
  import type { ChatChannelsPageController } from '$lib/features/chat-channels/state/chat-channels-controller.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import MutedStatusLine from '$lib/features/chat-channels/shared/MutedStatusLine.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  const SCROLL_BOTTOM_THRESHOLD_PX = 32;

  type Props = {
    /** The shared chat engine (same `getChatEngine()` singleton both surfaces bind). */
    ctrl: ChatChannelsPageController;
    /** Channel-select change handler (page syncs URL; overlay reloads only). */
    onChannelChange: () => void | Promise<void>;
    /** Refresh handler (page = refreshCurrent; overlay = refreshConversation). */
    onRefresh: () => void | Promise<void>;
    /** Compact overlay: hide the identity + toolbar header row (default shown on /chats). */
    showHeader?: boolean;
    /** Compact overlay: collapse composer extras (checkboxes + quick prompts) behind an arrow. */
    compactComposer?: boolean;
    /** Frameless/thin chrome for the floating overlay (drops the panel's own border, rounding,
     *  shadow and fat padding since the overlay window already provides the frame). */
    dense?: boolean;
  };

  let {
    ctrl,
    onChannelChange,
    onRefresh,
    showHeader = true,
    compactComposer = false,
    dense = false
  }: Props = $props();

  // Read-only projections of the controller surface onto the template.
  const channels = $derived(ctrl.channels);
  const channelsLoading = $derived(ctrl.channelsLoading);
  const channelsError = $derived(ctrl.channelsError);
  const messages = $derived(ctrl.messages);
  const messagesLoading = $derived(ctrl.messagesLoading);
  const messagesError = $derived(ctrl.messagesError);
  const liveUpdatesPaused = $derived(ctrl.liveUpdatesPaused);
  const agentTyping = $derived(ctrl.agentTyping);
  const agentVoiceGeneratingMessageId = $derived(ctrl.agentVoiceGeneratingMessageId);

  let messagesScroller = $state<HTMLDivElement | null>(null);
  /** Composer child instance — lets compact-overlay quick-prompt buttons refocus its textarea. */
  let composerRef = $state<{ focusDraft: () => void } | undefined>();
  let isPinnedToBottom = $state(true);
  let hasUnreadMessages = $state(false);
  let previousSelectedChannelId: string | null = null;
  let previousMessageCount = 0;
  let previousAgentTyping = false;

  function scrollerIsAtBottom(): boolean {
    if (!messagesScroller) return true;
    return (
      messagesScroller.scrollHeight - messagesScroller.scrollTop - messagesScroller.clientHeight <=
      SCROLL_BOTTOM_THRESHOLD_PX
    );
  }

  async function scrollMessagesToBottom(behavior: ScrollBehavior = 'auto') {
    await tick();
    if (!messagesScroller) return;
    messagesScroller.scrollTo({ top: messagesScroller.scrollHeight, behavior });
    isPinnedToBottom = true;
    hasUnreadMessages = false;
  }

  function handleMessagesScroll() {
    isPinnedToBottom = scrollerIsAtBottom();
    if (isPinnedToBottom) {
      hasUnreadMessages = false;
    }
  }

  $effect(() => {
    const channelChanged = ctrl.selectedChannelId !== previousSelectedChannelId;
    const countIncreased = !channelChanged && messages.length > previousMessageCount;
    const typingStarted = agentTyping && !previousAgentTyping;
    const firstLoad = messages.length > 0 && (channelChanged || previousMessageCount === 0);
    const shouldStickToBottom = firstLoad || isPinnedToBottom;

    previousSelectedChannelId = ctrl.selectedChannelId;
    previousMessageCount = messages.length;
    previousAgentTyping = agentTyping;

    if (messages.length === 0) {
      isPinnedToBottom = true;
      hasUnreadMessages = false;
      return;
    }

    if (shouldStickToBottom && (messages.length > 0 || typingStarted)) {
      void scrollMessagesToBottom();
      return;
    }
    if (countIncreased) {
      hasUnreadMessages = true;
    }
  });

  const inboundAgentMetaByReplyId = $derived.by(() => agentMetadataByReplyId(messages));

  /** Compact overlay quick-prompt: fill the draft and refocus the composer's textarea. */
  function applyQuickPromptCompact(text: string) {
    ctrl.draftMessage = text;
    composerRef?.focusDraft();
  }
</script>

<section
  class={cn(
    'flex h-full min-h-0 flex-1 flex-col overflow-hidden',
    dense ? 'gap-2 p-2' : 'gap-4 rounded-lg border bg-card p-5 shadow-sm'
  )}
>
  {#if showHeader}
    <ChatMessagesToolbar {ctrl} {dense} {onChannelChange} {onRefresh} />
    {#if compactComposer && ctrl.selectedChannelId}
      <!-- Compact overlay: surface the composer options here (just under the channel
           selector / toolbar) instead of behind an arrow above the input. -->
      <div class="shrink-0 space-y-1.5 border-border border-t pt-2">
        <ChatComposerOptions {ctrl} onPickQuickPrompt={applyQuickPromptCompact} />
      </div>
    {/if}
  {/if}

  <div class={cn('flex min-h-0 flex-1 flex-col overflow-hidden', dense ? 'gap-2' : 'gap-4')}>
    {#if channelsLoading}
      <InlineLoading label="Loading chat channels…" class="shrink-0" />
    {:else if channelsError}
      <InlineDestructiveAlert class="shrink-0" title="Could not load chat channels" message={channelsError} />
    {:else if channels.length === 0}
      <InlineEmptyState
        message="No conversation channels yet."
        hint="Create one on the Channels tab to start chatting."
        class="shrink-0"
      >
        {#snippet icon()}<MessagesSquare size={22} />{/snippet}
      </InlineEmptyState>
    {:else if messagesLoading}
      <InlineLoading label="Loading messages…" class="shrink-0" />
    {:else if messagesError}
      <InlineDestructiveAlert class="shrink-0" title="Could not load messages" message={messagesError} />
    {:else}
      <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden">
        {#if liveUpdatesPaused}
          <MutedStatusLine text="Live updates paused - retrying" class="shrink-0" />
        {/if}
        {#if messages.length === 0}
          <div class="flex min-h-0 min-w-0 flex-1 items-center justify-center">
            <InlineEmptyState
              message="No messages in this channel yet."
              hint="Send a message below to get started."
              class="w-full max-w-sm"
            >
              {#snippet icon()}<MessageCircle size={22} />{/snippet}
            </InlineEmptyState>
          </div>
        {:else}
          <div class="relative min-h-0 min-w-0 flex-1">
            <div
              bind:this={messagesScroller}
              class={cn(
                'h-full min-h-0 min-w-0 overflow-y-auto rounded-md bg-background/45',
                dense ? 'p-2' : 'border p-4'
              )}
              onscroll={handleMessagesScroll}
            >
              <div class="grid max-w-3xl gap-3">
                {#each messages as message (message.id)}
                  <ChatMessageBubble
                    {message}
                    {messages}
                    {inboundAgentMetaByReplyId}
                    selectedChannelId={ctrl.selectedChannelId}
                    {agentVoiceGeneratingMessageId}
                    showAgentTokensUi={ctrl.showAgentTokensUi}
                    showAgentToolsUi={ctrl.showAgentToolsUi}
                  />
                {/each}
                {#if agentTyping}
                  <div
                    class="flex w-full justify-start"
                    in:fly={{ y: 8, duration: 160 }}
                    aria-label="Agent is typing"
                  >
                    <div
                      class="flex items-center gap-1.5 rounded-2xl border border-border bg-secondary px-4 py-3 text-secondary-foreground shadow-sm dark:border-border dark:bg-secondary/40 dark:text-foreground dark:ring-1 dark:ring-border/80"
                    >
                      <span class="size-1.5 animate-bounce rounded-full bg-current opacity-55"></span>
                      <span
                        class="size-1.5 animate-bounce rounded-full bg-current opacity-70 [animation-delay:120ms]"
                      ></span>
                      <span
                        class="size-1.5 animate-bounce rounded-full bg-current opacity-85 [animation-delay:240ms]"
                      ></span>
                    </div>
                  </div>
                {/if}
              </div>
            </div>
            {#if hasUnreadMessages}
              <Button
                size="sm"
                variant="secondary"
                class="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 shadow-lg"
                onclick={() => void scrollMessagesToBottom('smooth')}
              >
                <ArrowDown size={14} /> New unread Messages
              </Button>
            {/if}
          </div>
        {/if}
        {#if ctrl.selectedChannelId && channels.length > 0 && !channelsError}
          <ChatMessageComposer bind:this={composerRef} {ctrl} {dense} {compactComposer} />
        {/if}
      </div>
    {/if}
  </div>
</section>
