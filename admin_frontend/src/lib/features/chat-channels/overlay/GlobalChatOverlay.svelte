<script lang="ts">
  import { Maximize2, Minimize2, MessagesSquare, Settings2, SquareArrowOutUpRight, X } from '@lucide/svelte';
  import { base } from '$app/paths';
  import { getChatEngine } from '$lib/features/chat-channels/state/chat-engine-singleton.svelte';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import ChatChannelsMessagesPanel from '$lib/features/chat-channels/messages/ChatChannelsMessagesPanel.svelte';
  import {
    cycleChatAudioSpeed,
    formatChatAudioSpeedLabel,
    chatAudioPlaybackRate
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import { cn } from '$lib/utils';

  const engine = getChatEngine();

  // Lease polling to the overlay whenever it is open. Load the conversation once on
  // the closed→open transition. No URL writes: the overlay floats over arbitrary pages.
  // Open/close is driven solely by the header toggle button in AdminShell.
  let wasOpen = false;
  $effect(() => {
    const isOpen = chatOverlay.open;
    engine.setOverlayActive(isOpen);
    if (isOpen && !wasOpen) void engine.ensureConversationLoaded();
    wasOpen = isOpen;
  });

  /** Settings gear reveals the panel's toolbar (channel switch, clear, speed, refresh). */
  let settingsOpen = $state(false);

  /** Window-chrome positioning per mode (full ↔ partial). Non-modal at z-40: above the
   *  fullscreen Knowledge Graph (z-30, so chat stays on top there) yet below modal dialogs
   *  (z-50) so a confirm triggered from here still stacks on top. */
  const shellClass = $derived(
    chatOverlay.mode === 'full'
      ? 'right-0 top-16 bottom-0 w-full sm:w-[420px] rounded-none border-y-0 border-r-0'
      : 'right-4 bottom-0 h-[min(60vh,560px)] w-[min(380px,calc(100vw-2rem))] rounded-t-xl'
  );

  const headerTitle = $derived(engine.messagesHeaderChannelName ?? 'Chat');

  /** "Open as full page" target — the /chats Messages tab. Real anchor so middle-click works. */
  const chatsHref = `${base}/chats/?tab=messages`;
</script>

{#if chatOverlay.open}
  <section
    class={cn(
      'fixed z-40 flex flex-col border border-border bg-card text-card-foreground shadow-2xl shadow-black/30',
      shellClass
    )}
    aria-label="Chat overlay"
  >
    <!-- Title bar. Open/close lives on the AdminShell header toggle, so no close/minimize here. -->
    <header
      class="flex min-h-11 shrink-0 items-center gap-2 border-b bg-background/60 px-3"
    >
      {#if engine.messagesHeaderPhotoSrc}
        <img
          src={engine.messagesHeaderPhotoSrc}
          alt=""
          class="size-7 shrink-0 rounded-full border border-border object-cover"
          title={engine.messagesHeaderChannelHint}
        />
      {:else}
        <MessagesSquare size={17} class="shrink-0 text-primary" aria-hidden="true" />
      {/if}
      <span class="min-w-0 flex-1 truncate font-sans text-sm font-medium">{headerTitle}</span>

      <div class="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          class={cn(
            'grid size-7 place-items-center rounded-md transition-colors hover:bg-accent hover:text-accent-foreground',
            settingsOpen ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
          )}
          aria-label={settingsOpen ? 'Hide chat settings' : 'Show chat settings'}
          aria-pressed={settingsOpen}
          title="Settings"
          onclick={() => (settingsOpen = !settingsOpen)}
        >
          <Settings2 size={15} aria-hidden="true" />
        </button>
        {#if chatOverlay.mode !== 'full'}
          <button
            type="button"
            class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            onclick={() => chatOverlay.setMode('full')}
            aria-label="Expand to full height"
            title="Full height"
          >
            <Maximize2 size={15} aria-hidden="true" />
          </button>
        {:else}
          <button
            type="button"
            class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            onclick={() => chatOverlay.setMode('partial')}
            aria-label="Restore to window"
            title="Window"
          >
            <Minimize2 size={15} aria-hidden="true" />
          </button>
        {/if}
        <a
          class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          href={chatsHref}
          onclick={() => chatOverlay.close()}
          aria-label="Open chat as full page"
          title="Open as full page"
        >
          <SquareArrowOutUpRight size={15} aria-hidden="true" />
        </a>
        <button
          type="button"
          class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          onclick={() => chatOverlay.close()}
          aria-label="Close chat"
          title="Close"
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>
    </header>

    <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <ChatChannelsMessagesPanel
          bind:selectedChannelId={engine.selectedChannelId}
          bind:requestVoiceReplyUi={engine.requestVoiceReplyUi}
          bind:useKnowledgeUi={engine.useKnowledgeUi}
          bind:disableToolsUi={engine.disableToolsUi}
          bind:showAgentTokensUi={engine.showAgentTokensUi}
          bind:showAgentToolsUi={engine.showAgentToolsUi}
          bind:draftMessage={engine.draftMessage}
          channels={engine.channels}
          channelsLoading={engine.channelsLoading}
          channelsError={engine.channelsError}
          messages={engine.messages}
          messagesLoading={engine.messagesLoading}
          messagesError={engine.messagesError}
          liveUpdatesPaused={engine.liveUpdatesPaused}
          agentTyping={engine.agentTyping}
          agentVoiceGeneratingMessageId={engine.agentVoiceGeneratingMessageId}
          busy={engine.busy}
          headerPhotoSrc={engine.messagesHeaderPhotoSrc}
          headerChannelHint={engine.messagesHeaderChannelHint}
          headerChannelName={engine.messagesHeaderChannelName}
          headerCharacterLabel={engine.messagesHeaderCharacterName}
          headerDeviceId={engine.messagesHeaderDeviceId}
          hasSelectedChannel={engine.selectedChannelExists}
          recordingStartedAt={engine.recordingStartedAt}
          composingBusy={engine.composingBusy}
          audioSpeedLabel={formatChatAudioSpeedLabel($chatAudioPlaybackRate)}
          onChannelChange={() => void engine.reloadMessages()}
          onClearMessages={() => engine.openClearMessagesModal()}
          onRefresh={engine.refreshConversation}
          onCycleAudioSpeed={cycleChatAudioSpeed}
          onSubmitDraft={engine.submitDraftText}
          onBeginRecording={engine.beginRecording}
          onFinalizeRecording={engine.finalizeRecording}
          onDiscardRecording={engine.discardRecording}
          voiceReplyCheckboxDisabled={engine.voiceReplyCheckboxDisabled}
          voiceReplyCheckboxHint={engine.voiceReplyCheckboxHint}
          showHeader={settingsOpen}
          compactComposer={true}
          dense={true}
        />
      </div>
  </section>
{/if}
