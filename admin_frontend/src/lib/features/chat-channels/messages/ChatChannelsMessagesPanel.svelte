<script lang="ts">
  import { tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import {
    ArrowDown,
    BarChart3,
    FileX2,
    ImageIcon,
    Mic,
    RefreshCw,
    Send,
    Square,
    Volume2,
    Wrench
  } from '@lucide/svelte';
  import {
    historyMessageFirstAudio,
    historyMessageText,
    type ChatChannelRow,
    type ChatHistoryMessage
  } from '$lib/api/chat-channels';
  import ChatMessageAttachmentAudio from '$lib/features/chat-channels/ChatMessageAttachmentAudio.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import AgentTokenCounter from '$lib/features/chat-channels/messages/AgentTokenCounter.svelte';
  import AgentToolStack from '$lib/features/chat-channels/messages/AgentToolStack.svelte';
  import {
    agentMetadataByReplyId,
    agentCostLabel,
    agentElapsedLabel,
    agentInputTokensIncludingCached,
    agentOutputTokens,
    agentTokensShouldAnimate,
    agentTools,
    messageAgentMetadata,
    telemetryBreakdownTitle
  } from '$lib/features/chat-channels/messages/agent-message-meta';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import MutedStatusLine from '$lib/features/chat-channels/shared/MutedStatusLine.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ServerStartingBanner from '$lib/runtime/ServerStartingBanner.svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SELECT, ADMIN_TEXTAREA } from '$lib/styling/admin-tokens';

  const SCROLL_BOTTOM_THRESHOLD_PX = 32;

  /** Sample prompts — click a number to replace the draft box (voice-reply UX smoke tests). */
  const QUICK_PROMPT_TEMPLATES = [
    'What is the capital of Spain? Reply with one word only.',
    'Who experimented with lightning and electricity using a kite (full name)? Reply with one sentence only.',
    'What is 8 × 7? Reply with one word only.',
    'What is photosynthesis in one sentence only?',
    'Name a gas we breathe out. Reply with one word only.'
  ] as const;

  type Props = {
    channels: ChatChannelRow[];
    channelsLoading: boolean;
    channelsError: string | null;
    messages: ChatHistoryMessage[];
    messagesLoading: boolean;
    messagesError: string | null;
    liveUpdatesPaused: boolean;
    agentTyping: boolean;
    agentVoiceGeneratingMessageId: string | null;
    busy: boolean;
    /** Header thumbnail: character browse photo only (no channel image). */
    headerPhotoSrc: string | null;
    /** Tooltip for avatar (character · channel · id). */
    headerChannelHint: string;
    /** Primary header title: selected channel name. */
    headerChannelName: string | null;
    /** Subtitle: character label when a channel is selected. */
    headerCharacterLabel: string | null;
    headerDeviceId: string | null;
    hasSelectedChannel: boolean;
    selectedChannelId: string | null;
    recordingStartedAt: number | null;
    composingBusy: boolean;
    audioSpeedLabel: string;
    onChannelChange: () => void | Promise<void>;
    onClearMessages: () => void;
    onRefresh: () => void | Promise<void>;
    onCycleAudioSpeed: () => void;
    onSubmitDraft: () => void | Promise<void>;
    onBeginRecording: () => void | Promise<void>;
    onFinalizeRecording: () => void | Promise<void>;
    onDiscardRecording: () => void | Promise<void>;
    requestVoiceReplyUi: boolean;
    useKnowledgeUi: boolean;
    draftMessage: string;
    voiceReplyCheckboxDisabled: boolean;
    voiceReplyCheckboxHint: string;
    /** Toggle agent token/cost stats on bubbles. */
    showAgentTokensUi?: boolean;
    /** Toggle agent tool stack on bubbles. */
    showAgentToolsUi?: boolean;
    /** Compact overlay: hide the identity + toolbar header row (default shown on /chats). */
    showHeader?: boolean;
    /** Compact overlay: collapse composer extras (checkboxes + quick prompts) behind an arrow. */
    compactComposer?: boolean;
    /** Frameless/thin chrome for the floating overlay (drops the panel's own border, rounding,
     *  shadow and fat padding since the overlay window already provides the frame). */
    dense?: boolean;
  };

  let {
    channels,
    channelsLoading,
    channelsError,
    messages,
    messagesLoading,
    messagesError,
    liveUpdatesPaused,
    agentTyping,
    agentVoiceGeneratingMessageId,
    busy,
    headerPhotoSrc,
    headerChannelHint,
    headerChannelName,
    headerCharacterLabel,
    headerDeviceId,
    hasSelectedChannel,
    selectedChannelId = $bindable(),
    recordingStartedAt,
    composingBusy,
    audioSpeedLabel,
    onChannelChange,
    onClearMessages,
    onRefresh,
    onCycleAudioSpeed,
    onSubmitDraft,
    onBeginRecording,
    onFinalizeRecording,
    onDiscardRecording,
    requestVoiceReplyUi = $bindable(),
    useKnowledgeUi = $bindable(true),
    showAgentTokensUi = $bindable(true),
    showAgentToolsUi = $bindable(true),
    draftMessage = $bindable(),
    voiceReplyCheckboxDisabled,
    voiceReplyCheckboxHint,
    showHeader = true,
    compactComposer = false,
    dense = false
  }: Props = $props();

  let messagesScroller = $state<HTMLDivElement | null>(null);
  let draftTextareaEl = $state<HTMLTextAreaElement | null>(null);
  let isPinnedToBottom = $state(true);
  let hasUnreadMessages = $state(false);
  let previousSelectedChannelId: string | null = null;
  let previousMessageCount = 0;
  let previousAgentTyping = false;
  let focusedReadyChannelId: string | null = null;

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

  async function focusDraftTextarea() {
    await tick();
    draftTextareaEl?.focus();
  }

  async function submitDraftAndRefocus() {
    await onSubmitDraft();
    await focusDraftTextarea();
  }

  async function finalizeRecordingAndRefocus() {
    await onFinalizeRecording();
    await focusDraftTextarea();
  }

  function handleMessagesScroll() {
    isPinnedToBottom = scrollerIsAtBottom();
    if (isPinnedToBottom) {
      hasUnreadMessages = false;
    }
  }

  $effect(() => {
    const channelChanged = selectedChannelId !== previousSelectedChannelId;
    const countIncreased = !channelChanged && messages.length > previousMessageCount;
    const typingStarted = agentTyping && !previousAgentTyping;
    const firstLoad = messages.length > 0 && (channelChanged || previousMessageCount === 0);
    const shouldStickToBottom = firstLoad || isPinnedToBottom;

    previousSelectedChannelId = selectedChannelId;
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

  $effect(() => {
    if (
      !selectedChannelId ||
      messagesLoading ||
      composingBusy ||
      recordingStartedAt !== null ||
      focusedReadyChannelId === selectedChannelId
    ) {
      return;
    }
    focusedReadyChannelId = selectedChannelId;
    void focusDraftTextarea();
  });

  /** Tick while recording so elapsed seconds update without touching controller state. */
  let recordingNowPerf = $state(0);
  $effect(() => {
    if (recordingStartedAt === null) return;
    recordingNowPerf = performance.now();
    const id = window.setInterval(() => {
      recordingNowPerf = performance.now();
    }, 250);
    return () => window.clearInterval(id);
  });

  const recordingElapsedLabel = $derived.by(() => {
    if (recordingStartedAt === null) return '';
    const sec = Math.max(0, Math.floor((recordingNowPerf - recordingStartedAt) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
  });

  function applyQuickPromptTemplate(index: number) {
    const text = QUICK_PROMPT_TEMPLATES[index];
    if (text === undefined) return;
    draftMessage = text;
    void focusDraftTextarea();
  }

  const inboundAgentMetaByReplyId = $derived.by(() => agentMetadataByReplyId(messages));

  function resolvedAgentMetadata(message: ChatHistoryMessage, isUser: boolean) {
    return messageAgentMetadata(message) ?? (!isUser ? inboundAgentMetaByReplyId.get(message.id) ?? null : null);
  }

  function hasVisibleAgentTelemetry(agent: ReturnType<typeof messageAgentMetadata>): boolean {
    return Boolean(
      agent &&
        (agentOutputTokens(agent) + agentInputTokensIncludingCached(agent) > 0 ||
          agentCostLabel(agent) ||
          agentElapsedLabel(agent))
    );
  }

  function shouldShowAgentTelemetry(
    message: ChatHistoryMessage,
    agent: ReturnType<typeof messageAgentMetadata>,
    isUser: boolean
  ): boolean {
    if (!agent || !hasVisibleAgentTelemetry(agent)) return false;
    if (!isUser) return true;
    const replyId = agent.reply_id;
    return !messages.some(
      (candidate) =>
        candidate.sender_type !== 'user' &&
        candidate.id === replyId &&
        hasVisibleAgentTelemetry(messageAgentMetadata(candidate))
    );
  }
</script>

<section
  class={cn(
    'flex h-full min-h-0 flex-1 flex-col overflow-hidden',
    dense ? 'gap-2 p-2' : 'gap-4 rounded-lg border bg-card p-5 shadow-sm'
  )}
>
  <!-- Composer options (voice/knowledge toggles + sample prompts). Rendered at the top
       beside the channel selector in the compact overlay, or above the input on /chats. -->
  {#snippet composerExtras()}
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
        <label
          class={cn(
            'flex items-center gap-2 text-xs text-muted-foreground',
            voiceReplyCheckboxDisabled ? 'cursor-not-allowed opacity-80' : 'cursor-pointer'
          )}
          title={voiceReplyCheckboxHint ||
            'Ask the agent to reply with synthesized speech (same as mobile routing flag).'}
        >
          <input
            type="checkbox"
            bind:checked={requestVoiceReplyUi}
            disabled={voiceReplyCheckboxDisabled}
            class="accent-primary h-4 w-4 shrink-0 disabled:cursor-not-allowed"
          />
          Get voice reply
        </label>
        <label
          class="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground"
          title="Augment this message's reply with relevant workspace knowledge (sent per-message)."
        >
          <input
            type="checkbox"
            bind:checked={useKnowledgeUi}
            class="accent-primary h-4 w-4 shrink-0"
          />
          Use knowledge
        </label>
      </div>
      <div
        class="flex shrink-0 items-center gap-1"
        role="group"
        aria-label="Fill message box with a sample prompt"
      >
        {#each QUICK_PROMPT_TEMPLATES as prompt, i (i)}
          <button
            type="button"
            class="grid size-8 place-items-center rounded border border-input bg-background font-sans text-xs font-semibold tabular-nums text-muted-foreground shadow-xs transition-colors hover:border-primary/50 hover:bg-primary/10 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            title={prompt}
            aria-label={`Sample prompt ${i + 1}: ${prompt}`}
            disabled={composingBusy}
            onclick={() => applyQuickPromptTemplate(i)}
          >
            {i + 1}
          </button>
        {/each}
      </div>
    </div>
    {#if voiceReplyCheckboxDisabled && voiceReplyCheckboxHint}
      <p class="max-w-prose text-[11px] leading-snug text-muted-foreground">
        {voiceReplyCheckboxHint}
      </p>
    {/if}
  {/snippet}

  {#if showHeader}
  <div class="flex shrink-0 min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    {#if !dense}
    <div class="flex min-w-0 items-center gap-3">
      {#if headerPhotoSrc}
        <img
          src={headerPhotoSrc}
          alt=""
          class="size-14 shrink-0 rounded-xl border bg-muted object-cover"
          title={headerChannelHint}
        />
      {:else}
        <div
          class="flex size-14 shrink-0 items-center justify-center rounded-xl border border-dashed bg-muted text-muted-foreground"
          aria-hidden="true"
          title={headerChannelHint}
        >
          <ImageIcon size={24} />
        </div>
      {/if}
      <div class="min-w-0">
        <h3 class="truncate text-lg font-semibold leading-tight" title={headerChannelHint}>
          {headerChannelName ?? 'Messages'}
        </h3>
        {#if hasSelectedChannel && headerCharacterLabel}
          <p class="mt-0.5 truncate font-sans text-sm leading-tight" title={headerChannelHint}>
            <span class="font-semibold text-foreground">{headerCharacterLabel}</span>
            {#if headerDeviceId}
              <span class="text-muted-foreground"> · </span>
              <span class="font-mono text-[11px] text-muted-foreground">{headerDeviceId}</span>
            {/if}
          </p>
        {:else}
          <span class="mt-0.5 block font-sans text-sm text-muted-foreground">No channel selected</span>
        {/if}
      </div>
    </div>
    {/if}
    <div class={cn('flex flex-wrap items-center gap-2', dense ? 'w-full' : 'shrink-0')}>
      {#if channels.length > 0}
        <select
          class={cn(ADMIN_SELECT, dense ? 'w-full' : 'min-w-56')}
          bind:value={selectedChannelId}
          onchange={() => onChannelChange()}
          aria-label="Message channel"
          title={headerChannelHint}
        >
          {#each channels as channel (channel.id)}
            <option value={String(channel.id)}>{channel.name} (id {channel.id})</option>
          {/each}
        </select>
      {/if}
      <Button
        variant="outline"
        size="icon"
        class="border-destructive/60 text-destructive hover:bg-destructive/10"
        disabled={busy || !selectedChannelId || channelsLoading}
        onclick={onClearMessages}
        aria-label="Clear channel"
        title="Remove all messages in this channel"
      >
        <FileX2 size={15} />
      </Button>
      <Button variant="outline" onclick={onCycleAudioSpeed} title="Cycle playback speed (applies to all clips)">
        {audioSpeedLabel}
      </Button>
      <Button
        variant="outline"
        size="icon"
        class={cn(!showAgentTokensUi && 'opacity-50')}
        aria-label={showAgentTokensUi ? 'Hide message stats' : 'Show message stats'}
        aria-pressed={showAgentTokensUi}
        title={showAgentTokensUi ? 'Hide token & cost stats' : 'Show token & cost stats'}
        onclick={() => {
          showAgentTokensUi = !showAgentTokensUi;
        }}
      >
        <BarChart3 size={15} />
      </Button>
      <Button
        variant="outline"
        size="icon"
        class={cn(!showAgentToolsUi && 'opacity-50')}
        aria-label={showAgentToolsUi ? 'Hide message tools' : 'Show message tools'}
        aria-pressed={showAgentToolsUi}
        title={showAgentToolsUi ? 'Hide tool stack' : 'Show tool stack'}
        onclick={() => {
          showAgentToolsUi = !showAgentToolsUi;
        }}
      >
        <Wrench size={15} />
      </Button>
      <Button
        variant="outline"
        size="icon"
        aria-label="Refresh messages"
        title="Refresh messages"
        onclick={() => onRefresh()}
      >
        <RefreshCw size={15} />
      </Button>
    </div>
  </div>
  {#if compactComposer && selectedChannelId}
    <!-- Compact overlay: surface the composer options here (just under the channel
         selector / toolbar) instead of behind an arrow above the input. -->
    <div class="shrink-0 space-y-1.5 border-border border-t pt-2">
      {@render composerExtras()}
    </div>
  {/if}
  {/if}

  <div class={cn('flex min-h-0 flex-1 flex-col overflow-hidden', dense ? 'gap-2' : 'gap-4')}>
    {#if channelsLoading}
      <InlineLoading label="Loading chat channels…" class="shrink-0" />
    {:else if channelsError}
      <InlineDestructiveAlert class="shrink-0" title="Could not load chat channels" message={channelsError} />
    {:else if channels.length === 0}
      <MutedStatusLine
        text="No conversation channels. Create one on the Channels tab."
        class="shrink-0"
      />
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
          <div
            class="flex min-h-0 min-w-0 flex-1 items-center justify-center rounded-md border bg-background/45 p-4"
          >
            <MutedStatusLine text="No messages in this channel yet." />
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
                  {@const isUser = message.sender_type === 'user'}
                  {@const textBody = historyMessageText(message)}
                  {@const audioItem = historyMessageFirstAudio(message)}
                  {@const agentMeta = resolvedAgentMetadata(message, isUser)}
                  {@const showAgentMeta = shouldShowAgentTelemetry(message, agentMeta, isUser)}
                  {@const outputTokens = showAgentMeta ? agentOutputTokens(agentMeta) : 0}
                  {@const inputTokensIncl = showAgentMeta ? agentInputTokensIncludingCached(agentMeta) : 0}
                  {@const toolCalls = showAgentMeta ? agentTools(agentMeta) : []}
                  {@const tokenCountAnimates =
                    showAgentMeta && agentTokensShouldAnimate(agentMeta)}
                  {@const costLabel = showAgentMeta ? agentCostLabel(agentMeta) : ''}
                  {@const elapsedLabel = showAgentMeta ? agentElapsedLabel(agentMeta) : ''}
                  {@const tokenTooltip = telemetryBreakdownTitle(agentMeta?.usage_total)}
                  {@const showToolsUi = showAgentToolsUi && toolCalls.length > 0}
                  {@const showTokensUi =
                    showAgentTokensUi &&
                    (outputTokens > 0 || inputTokensIncl > 0 || costLabel || elapsedLabel)}
                  <div
                    class={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}
                    in:fly={{ y: 8, duration: 160 }}
                  >
                    <div
                      class={cn(
                        'grid max-w-[85%] gap-1.5 rounded-2xl px-4 py-2.5 shadow-sm',
                        isUser
                          ? 'bg-primary text-primary-foreground'
                          : 'border border-border bg-secondary text-secondary-foreground dark:border-border dark:bg-secondary/40 dark:text-foreground dark:ring-1 dark:ring-border/80'
                      )}
                    >
                      {#if showToolsUi}
                        <AgentToolStack tools={toolCalls} />
                      {/if}
                      {#if textBody}
                        <div class="flex min-w-0 items-start gap-2">
                          <p class="min-w-0 whitespace-pre-wrap break-words font-sans text-sm">
                            {textBody}
                          </p>
                          {#if !isUser && !audioItem && agentVoiceGeneratingMessageId === message.id}
                            <Volume2
                              size={15}
                              class="mt-0.5 shrink-0 animate-pulse opacity-75 [animation-duration:1800ms]"
                              aria-label="Voice reply is being generated"
                            />
                          {/if}
                        </div>
                      {:else if !audioItem}
                        <p class="whitespace-pre-wrap break-words font-sans text-sm opacity-80">
                          No text body
                        </p>
                      {/if}
                      {#if audioItem && selectedChannelId}
                        <ChatMessageAttachmentAudio
                          channelId={Number(selectedChannelId)}
                          externalMessageId={message.id}
                          audioItem={audioItem}
                        />
                      {/if}
                      {#if showTokensUi || message.created_at}
                        <!-- Stack telemetry + timestamp on their own lines so the stats
                             never wrap awkwardly inside narrow bubbles (e.g. the overlay). -->
                        <div
                          class={cn(
                            'flex min-w-0 flex-col gap-0.5 pt-0.5',
                            isUser ? 'items-end' : 'items-start'
                          )}
                        >
                          {#if showTokensUi}
                            <AgentTokenCounter
                              inputValue={inputTokensIncl}
                              outputValue={outputTokens}
                              {costLabel}
                              {elapsedLabel}
                              animate={tokenCountAnimates}
                              tooltip={tokenTooltip}
                              className={isUser ? 'text-amber-100' : 'text-emerald-700 dark:text-emerald-300'}
                              costClassName={
                                isUser
                                  ? 'font-semibold text-cyan-200'
                                  : 'font-semibold text-violet-600 dark:text-violet-400'
                              }
                            />
                          {/if}
                          {#if message.created_at}
                          <span
                            class={cn(
                              'shrink-0 tabular-nums font-sans text-[10px] leading-none opacity-40',
                              // Right-align the agent's timestamp (token stats stay left).
                              isUser ? 'opacity-50' : 'self-end'
                            )}
                          >
                            {formatChatTimestamp(message.created_at)}
                          </span>
                          {/if}
                        </div>
                      {/if}
                    </div>
                  </div>
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
        {#if selectedChannelId && channels.length > 0 && !channelsError}
          <div
            class={cn(
              'shrink-0 font-sans text-sm',
              dense ? 'space-y-1.5' : 'space-y-2 border-border border-t pt-3'
            )}
          >
            <ServerStartingBanner />
            {#if !compactComposer}
              {@render composerExtras()}
            {/if}
            {#if recordingStartedAt !== null}
              <div class="flex flex-wrap items-center gap-3">
                <span class="font-medium text-destructive tabular-nums">
                  Recording… {#if recordingElapsedLabel}<span class="opacity-90">({recordingElapsedLabel})</span>{/if}
                </span>
                <Button size="sm" onclick={() => void finalizeRecordingAndRefocus()} disabled={composingBusy}>
                  <Square size={14} /> Stop & send
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onclick={() => void onDiscardRecording()}
                  disabled={composingBusy}
                >
                  Cancel
                </Button>
              </div>
            {:else}
              <div class={cn('flex gap-2', dense ? 'items-end' : 'items-stretch')}>
                <textarea
                  bind:this={draftTextareaEl}
                  class={cn(
                    ADMIN_TEXTAREA,
                    'min-w-0 flex-1 placeholder:text-muted-foreground/40',
                    !dense && 'md:min-w-[16rem]'
                  )}
                  placeholder="Ask Hiro Anything"
                  rows={dense ? 4 : 2}
                  bind:value={draftMessage}
                  onkeydown={(ev) => {
                    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
                      ev.preventDefault();
                      if (!serverReadiness.ready) return;
                      void submitDraftAndRefocus();
                      return;
                    }
                    if (ev.key === 'Enter' && !ev.shiftKey) {
                      ev.preventDefault();
                      if (!serverReadiness.ready) return;
                      void submitDraftAndRefocus();
                    }
                  }}
                  disabled={composingBusy}
                ></textarea>
                <Button
                  class="h-11 min-w-11 self-stretch px-0"
                  title={serverReadiness.ready
                    ? 'Send message (Enter)'
                    : 'HiroServer is still starting — send will be available momentarily.'}
                  disabled={composingBusy || !draftMessage.trim() || !serverReadiness.ready}
                  onclick={() => void submitDraftAndRefocus()}
                >
                  <Send size={20} />
                </Button>
                <Button
                  variant="outline"
                  class="h-11 min-w-11 shrink-0 self-stretch border-destructive/50 px-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  title="Record voice message"
                  disabled={composingBusy}
                  aria-label="Record voice message"
                  onclick={() => void onBeginRecording()}
                >
                  <Mic size={20} strokeWidth={2.25} class="text-destructive" />
                </Button>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>
