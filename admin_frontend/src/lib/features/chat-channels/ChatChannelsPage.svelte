<script lang="ts">
  import { onMount } from 'svelte';
  import ChatChannelsBrowse from '$lib/features/chat-channels/browse/ChatChannelsBrowse.svelte';
  import ChatChannelEditorModal from '$lib/features/chat-channels/edit/ChatChannelEditorModal.svelte';
  import ChatChannelsMessagesPanel from '$lib/features/chat-channels/messages/ChatChannelsMessagesPanel.svelte';
  import ChatChannelClearMessagesModal from '$lib/features/chat-channels/modals/ChatChannelClearMessagesModal.svelte';
  import ChatChannelDeleteModal from '$lib/features/chat-channels/modals/ChatChannelDeleteModal.svelte';
  import ChatChannelDiscardModal from '$lib/features/chat-channels/modals/ChatChannelDiscardModal.svelte';
  import {
    cycleChatAudioSpeed,
    formatChatAudioSpeedLabel,
    chatAudioPlaybackRate
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import { createChatChannelsPageController } from '$lib/features/chat-channels/state/chat-channels-controller.svelte';
  import {
    CHAT_CHANNELS_PANEL_IDS,
    CHAT_CHANNELS_TAB_IDS,
    CHAT_CHANNELS_TABLIST_LABEL
  } from '$lib/features/chat-channels/shared/chat-channels-a11y';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  const ctrl = createChatChannelsPageController();

  /** Boot restores tab/channel via ``chat-channels-nav.ts`` (`readChatChannelsNavFromLocation`). */
  onMount(() => {
    void ctrl.mount();
    return () => {
      void ctrl.disposeActiveRecording();
    };
  });
</script>

<section class="flex h-full min-h-0 max-w-[1420px] flex-col gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Communication</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Chat channels</h2>
    </div>
    <div
      class="inline-flex rounded-lg border bg-card p-1"
      role="tablist"
      aria-label={CHAT_CHANNELS_TABLIST_LABEL}
    >
      <Button
        id={CHAT_CHANNELS_TAB_IDS.channels}
        class={cn(
          'shadow-none',
          ctrl.activeTab === 'channels' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={ctrl.activeTab === 'channels' ? 'secondary' : 'ghost'}
        role="tab"
        type="button"
        aria-controls={CHAT_CHANNELS_PANEL_IDS.channels}
        aria-selected={ctrl.activeTab === 'channels'}
        onclick={() => void ctrl.setActiveTab('channels')}
      >
        Channels
      </Button>
      <Button
        id={CHAT_CHANNELS_TAB_IDS.messages}
        class={cn(
          'shadow-none',
          ctrl.activeTab === 'messages' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={ctrl.activeTab === 'messages' ? 'secondary' : 'ghost'}
        role="tab"
        type="button"
        aria-controls={CHAT_CHANNELS_PANEL_IDS.messages}
        aria-selected={ctrl.activeTab === 'messages'}
        onclick={() => void ctrl.setActiveTab('messages')}
      >
        Messages
      </Button>
    </div>
  </div>

  <div
    id={CHAT_CHANNELS_PANEL_IDS.channels}
    class="flex min-h-0 min-w-0 flex-1 flex-col"
    role="tabpanel"
    aria-labelledby={CHAT_CHANNELS_TAB_IDS.channels}
    hidden={ctrl.activeTab !== 'channels'}
  >
    <ChatChannelsBrowse
      channels={ctrl.channels}
      channelsLoading={ctrl.channelsLoading}
      channelsError={ctrl.channelsError}
      onRefresh={ctrl.loadChannels}
      onAddChannel={ctrl.openCreate}
      onOpenMessages={(row) => void ctrl.openMessages(row)}
      onEditChannel={ctrl.openEdit}
      onDeleteChannel={(row) => (ctrl.deleteTarget = row)}
    />
  </div>
  <div
    id={CHAT_CHANNELS_PANEL_IDS.messages}
    class="flex min-h-0 min-w-0 flex-1 flex-col"
    role="tabpanel"
    aria-labelledby={CHAT_CHANNELS_TAB_IDS.messages}
    hidden={ctrl.activeTab !== 'messages'}
  >
    <ChatChannelsMessagesPanel
      bind:selectedChannelId={ctrl.selectedChannelId}
      bind:requestVoiceReplyUi={ctrl.requestVoiceReplyUi}
      bind:draftMessage={ctrl.draftMessage}
      channels={ctrl.channels}
      channelsLoading={ctrl.channelsLoading}
      channelsError={ctrl.channelsError}
      messages={ctrl.messages}
      messagesLoading={ctrl.messagesLoading}
      messagesError={ctrl.messagesError}
      busy={ctrl.busy}
      headerPhotoSrc={ctrl.messagesHeaderPhotoSrc}
      headerChannelHint={ctrl.messagesHeaderChannelHint}
      headerCharacterLabel={ctrl.messagesHeaderCharacterName}
      headerDeviceId={ctrl.messagesHeaderDeviceId}
      hasSelectedChannel={ctrl.selectedChannelExists}
      recordingStartedAt={ctrl.recordingStartedAt}
      composingBusy={ctrl.composingBusy}
      audioSpeedLabel={formatChatAudioSpeedLabel($chatAudioPlaybackRate)}
      onChannelChange={ctrl.handleChannelSelect}
      onClearMessages={() => ctrl.openClearMessagesModal()}
      onRefresh={ctrl.refreshCurrent}
      onCycleAudioSpeed={cycleChatAudioSpeed}
      onSubmitDraft={ctrl.submitDraftText}
      onBeginRecording={ctrl.beginRecording}
      onFinalizeRecording={ctrl.finalizeRecording}
      onDiscardRecording={ctrl.discardRecording}
      voiceReplyCheckboxDisabled={ctrl.voiceReplyCheckboxDisabled}
      voiceReplyCheckboxHint={ctrl.voiceReplyCheckboxHint}
    />
  </div>
</section>

<ToastHost toast={ctrl.toast} />

<ChatChannelClearMessagesModal
  open={ctrl.clearMessagesConfirmOpen}
  channelName={ctrl.clearMessagesChannelDisplayName}
  busy={ctrl.busy}
  onClose={() => ctrl.closeClearMessagesModal()}
  onConfirm={() => void ctrl.submitClearMessages()}
/>

<ChatChannelEditorModal
  open={ctrl.formOpen}
  title={ctrl.formTitle}
  busy={ctrl.busy}
  formMode={ctrl.formMode}
  bind:form={ctrl.form}
  bind:pendingPhotoDataUrl={ctrl.pendingPhotoDataUrl}
  modalChannelPhotoSrc={ctrl.modalChannelPhotoSrc}
  formError={ctrl.formError}
  characters={ctrl.characters}
  characterLabel={ctrl.characterLabel}
  onBeforeClose={ctrl.channelFormBeforeClose}
  onDismiss={() => ctrl.finalizeChannelForm()}
  onCancelExplicit={() => ctrl.cancelChannelFormExplicit()}
  onSubmit={() => void ctrl.submitForm()}
/>

<ChatChannelDiscardModal
  open={ctrl.discardConfirmOpen}
  onKeepEditing={() => ctrl.keepEditingAfterDismissAttempt()}
  onDiscard={() => ctrl.discardUnsavedChannelFormAndClose()}
/>

<ChatChannelDeleteModal
  target={ctrl.deleteTarget}
  busy={ctrl.busy}
  onClose={() => ctrl.closeDelete()}
  onConfirm={() => void ctrl.submitDelete()}
/>
