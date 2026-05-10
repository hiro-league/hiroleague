<script lang="ts">
  import {
    FileX2,
    ImageIcon,
    Mic,
    RefreshCw,
    Send,
    Square
  } from '@lucide/svelte';
  import {
    historyMessageFirstAudio,
    historyMessageText,
    type ChatChannelRow,
    type ChatHistoryMessage
  } from '$lib/api/chat-channels';
  import ChatMessageAttachmentAudio from '$lib/features/chat-channels/ChatMessageAttachmentAudio.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import InlineDestructiveAlert from '$lib/features/chat-channels/shared/InlineDestructiveAlert.svelte';
  import MutedStatusLine from '$lib/features/chat-channels/shared/MutedStatusLine.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    channels: ChatChannelRow[];
    channelsLoading: boolean;
    channelsError: string | null;
    messages: ChatHistoryMessage[];
    messagesLoading: boolean;
    messagesError: string | null;
    busy: boolean;
    /** Header thumbnail: character/channel photo or null for placeholder icon. */
    headerPhotoSrc: string | null;
    /** Tooltip strings for avatar and channel select. */
    headerChannelHint: string;
    /** Subtitle next to "Messages" when a channel is selected. */
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
    draftMessage: string;
    voiceReplyCheckboxDisabled: boolean;
    voiceReplyCheckboxHint: string;
  };

  let {
    channels,
    channelsLoading,
    channelsError,
    messages,
    messagesLoading,
    messagesError,
    busy,
    headerPhotoSrc,
    headerChannelHint,
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
    draftMessage = $bindable(),
    voiceReplyCheckboxDisabled,
    voiceReplyCheckboxHint
  }: Props = $props();

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
</script>

<section
  class="flex h-full min-h-0 flex-1 flex-col gap-4 overflow-hidden rounded-lg border bg-card p-5 shadow-sm"
>
  <div class="flex shrink-0 min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
        <h3 class="text-lg font-semibold leading-tight">Messages</h3>
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
    <div class="flex shrink-0 flex-wrap items-center gap-2">
      {#if channels.length > 0}
        <select
          class="h-9 min-w-56 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
        class="border-destructive/60 text-destructive hover:bg-destructive/10"
        disabled={busy || !selectedChannelId || channelsLoading}
        onclick={onClearMessages}
        title="Remove all messages in this channel"
      >
        <FileX2 size={15} /> Clear messages
      </Button>
      <Button variant="outline" onclick={onCycleAudioSpeed} title="Cycle playback speed (applies to all clips)">
        {audioSpeedLabel}
      </Button>
      <Button variant="outline" onclick={() => onRefresh()}
        ><RefreshCw size={15} /> Refresh</Button
      >
    </div>
  </div>

  <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
    {#if channelsLoading}
      <MutedStatusLine text="Loading chat channels..." class="shrink-0" />
    {:else if channelsError}
      <InlineDestructiveAlert class="shrink-0" title="Could not load chat channels" message={channelsError} />
    {:else if channels.length === 0}
      <MutedStatusLine
        text="No conversation channels. Create one on the Channels tab."
        class="shrink-0"
      />
    {:else if messagesLoading}
      <MutedStatusLine text="Loading messages..." class="shrink-0" />
    {:else if messagesError}
      <InlineDestructiveAlert class="shrink-0" title="Could not load messages" message={messagesError} />
    {:else}
      <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden">
        {#if messages.length === 0}
          <MutedStatusLine text="No messages in this channel yet." class="shrink-0" />
        {:else}
          <div class="min-h-0 min-w-0 flex-1 overflow-y-auto rounded-md border bg-background/45 p-4">
            <div class="grid max-w-3xl gap-3">
              {#each messages as message (message.id)}
                {@const isUser = message.sender_type === 'user'}
                {@const textBody = historyMessageText(message)}
                {@const audioItem = historyMessageFirstAudio(message)}
                <div class={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
                  <div
                    class={cn(
                      'grid max-w-[85%] gap-1.5 rounded-2xl px-4 py-2.5 shadow-sm',
                      isUser
                        ? 'bg-primary text-primary-foreground'
                        : 'border border-border bg-secondary text-secondary-foreground dark:border-border dark:bg-secondary/40 dark:text-foreground dark:ring-1 dark:ring-border/80'
                    )}
                  >
                    {#if textBody}
                      <p class="whitespace-pre-wrap break-words font-sans text-sm">{textBody}</p>
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
                    {#if message.created_at}
                      <div class="flex justify-end pt-0.5">
                        <span
                          class={cn(
                            'tabular-nums font-sans text-[10px] leading-none opacity-40',
                            isUser && 'opacity-50'
                          )}
                        >
                          {formatChatTimestamp(message.created_at)}
                        </span>
                      </div>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
        {#if selectedChannelId && channels.length > 0 && !channelsError}
          <div class="shrink-0 space-y-2 border-border border-t pt-3 font-sans text-sm">
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
            {#if voiceReplyCheckboxDisabled && voiceReplyCheckboxHint}
              <p class="max-w-prose text-[11px] leading-snug text-muted-foreground">
                {voiceReplyCheckboxHint}
              </p>
            {/if}
            {#if recordingStartedAt !== null}
              <div class="flex flex-wrap items-center gap-3">
                <span class="font-medium text-destructive tabular-nums">
                  Recording… {#if recordingElapsedLabel}<span class="opacity-90">({recordingElapsedLabel})</span>{/if}
                </span>
                <Button size="sm" onclick={() => void onFinalizeRecording()} disabled={composingBusy}>
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
              <div class="flex flex-wrap items-stretch gap-2">
                <textarea
                  class="focus-visible:ring-ring min-h-11 flex-1 resize-y rounded-md border border-input bg-background px-3 py-2.5 text-sm leading-snug outline-none focus-visible:ring-2 md:min-w-[16rem]"
                  placeholder="Send as workspace owner… (Enter to send, Shift+Enter for new line)"
                  rows="2"
                  bind:value={draftMessage}
                  onkeydown={(ev) => {
                    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
                      ev.preventDefault();
                      void onSubmitDraft();
                      return;
                    }
                    if (ev.key === 'Enter' && !ev.shiftKey) {
                      ev.preventDefault();
                      void onSubmitDraft();
                    }
                  }}
                  disabled={composingBusy}
                ></textarea>
                <Button
                  class="h-11 min-w-11 self-stretch px-0"
                  title="Send message (Enter)"
                  disabled={composingBusy || !draftMessage.trim()}
                  onclick={() => void onSubmitDraft()}
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
