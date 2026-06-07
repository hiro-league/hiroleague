<script lang="ts">
  import { onMount } from 'svelte';
  import { afterNavigate } from '$app/navigation';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import ChatChannelsBrowse from '$lib/features/chat-channels/browse/ChatChannelsBrowse.svelte';
  import ChatChannelEditorModal from '$lib/features/chat-channels/edit/ChatChannelEditorModal.svelte';
  import ChatChannelsMessagesPanel from '$lib/features/chat-channels/messages/ChatChannelsMessagesPanel.svelte';
  import ChatChannelDeleteModal from '$lib/features/chat-channels/modals/ChatChannelDeleteModal.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import {
    cycleChatAudioSpeed,
    formatChatAudioSpeedLabel,
    chatAudioPlaybackRate
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import { getChatEngine } from '$lib/features/chat-channels/state/chat-engine-singleton.svelte';
  import {
    CHAT_CHANNELS_PANEL_IDS,
    CHAT_CHANNELS_TAB_IDS,
    CHAT_CHANNELS_TABLIST_LABEL
  } from '$lib/features/chat-channels/shared/chat-channels-a11y';
  import type { ChatChannelsTabPreference } from '$lib/preferences/keys';

  // Shared engine — the same instance the global overlay binds. The page does NOT
  // own its lifecycle: it leases polling while the Messages tab is on screen and
  // releases the lease on unmount, but never disposes the shared engine.
  const ctrl = getChatEngine();

  /** Boot restores tab/channel via `createChatChannelsPreferences()`. */
  onMount(() => {
    void ctrl.mount();
    return () => {
      ctrl.setPageMessagesActive(false);
    };
  });

  // Same-route deep links (e.g. the overlay's "open full page" → ?tab=messages
  // while already on /chats) only change the URL; onMount won't re-run, so pick
  // up the new tab/channel here. Mirrors LogsPage/KnowledgePage/MemoriesPage.
  afterNavigate(() => {
    ctrl.syncNavFromUrl();
  });

  /** Lease live updates to the page only while the Messages tab is actually shown. */
  $effect(() => {
    ctrl.setPageMessagesActive(ctrl.activeTab === 'messages');
  });

  const tabDescriptors: readonly AdminTabDescriptor<ChatChannelsTabPreference>[] = [
    {
      id: 'channels',
      label: 'Channels',
      kind: 'pane',
      htmlId: CHAT_CHANNELS_TAB_IDS.channels,
      ariaControls: CHAT_CHANNELS_PANEL_IDS.channels
    },
    {
      id: 'messages',
      label: 'Messages',
      kind: 'pane',
      htmlId: CHAT_CHANNELS_TAB_IDS.messages,
      ariaControls: CHAT_CHANNELS_PANEL_IDS.messages
    }
  ];
</script>

<AdminPageHeader
  kicker="Communication"
  title="Chat channels"
  wrapperClass="flex h-full min-h-0 max-w-[1420px] flex-col gap-5"
>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel={CHAT_CHANNELS_TABLIST_LABEL}
      tabs={tabDescriptors}
      active={ctrl.activeTab}
      onSelect={(id) => void ctrl.setActiveTab(id)}
    />
  {/snippet}

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
      bind:useKnowledgeUi={ctrl.useKnowledgeUi}
      bind:disableToolsUi={ctrl.disableToolsUi}
      bind:showAgentTokensUi={ctrl.showAgentTokensUi}
      bind:showAgentToolsUi={ctrl.showAgentToolsUi}
      bind:draftMessage={ctrl.draftMessage}
      channels={ctrl.channels}
      channelsLoading={ctrl.channelsLoading}
      channelsError={ctrl.channelsError}
      messages={ctrl.messages}
      messagesLoading={ctrl.messagesLoading}
      messagesError={ctrl.messagesError}
      liveUpdatesPaused={ctrl.liveUpdatesPaused}
      agentTyping={ctrl.agentTyping}
      agentVoiceGeneratingMessageId={ctrl.agentVoiceGeneratingMessageId}
      busy={ctrl.busy}
      headerPhotoSrc={ctrl.messagesHeaderPhotoSrc}
      headerChannelHint={ctrl.messagesHeaderChannelHint}
      headerChannelName={ctrl.messagesHeaderChannelName}
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
</AdminPageHeader>

<!-- Toast host + clear-messages modal moved to AdminShell so they serve the global
     overlay too (single shared engine). Channel CRUD modals stay here (page-only). -->

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
  onCancelExplicit={() => void ctrl.cancelChannelFormExplicit()}
  onSubmit={() => void ctrl.submitForm()}
/>

<Dialog.Root
  open={ctrl.unsaved.unsavedModalOpen}
  onOpenChange={(next) => {
    if (!next) ctrl.unsaved.closeUnsavedModalContinueEditing();
  }}
>
  <Dialog.Content overlayClass="z-[60]" class="z-[60] sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Discard changes?</Dialog.Title>
      <Dialog.Description>
        You have unsaved edits for this conversation channel.
      </Dialog.Description>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">
      Discard them and close the editor, or keep editing.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={ctrl.unsaved.closeUnsavedModalContinueEditing}>
        Keep editing
      </Button>
      <Button variant="destructive" onclick={ctrl.unsaved.confirmUnsavedModalDiscard}>
        Discard
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<ChatChannelDeleteModal
  target={ctrl.deleteTarget}
  busy={ctrl.busy}
  onClose={() => ctrl.closeDelete()}
  onConfirm={() => void ctrl.submitDelete()}
/>
