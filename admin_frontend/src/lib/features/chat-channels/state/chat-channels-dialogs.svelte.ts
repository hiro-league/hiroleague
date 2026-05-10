import type { ChatChannelRow } from '$lib/api/chat-channels';

/**
 * Confirm / destructive modal flags for chat channels (clear thread, delete channel, discard editor).
 * Keeps open/close rules in one place; controller stays responsible for API side-effects.
 */
export function createChatChannelsDialogs(opts: { isBusy: () => boolean }) {
  let clearMessagesConfirmOpen = $state(false);
  let deleteTarget = $state<ChatChannelRow | null>(null);
  let discardConfirmOpen = $state(false);

  return {
    get clearMessagesConfirmOpen(): boolean {
      return clearMessagesConfirmOpen;
    },

    get deleteTarget(): ChatChannelRow | null {
      return deleteTarget;
    },
    set deleteTarget(v: ChatChannelRow | null) {
      deleteTarget = v;
    },

    get discardConfirmOpen(): boolean {
      return discardConfirmOpen;
    },

    openClearMessagesModal() {
      clearMessagesConfirmOpen = true;
    },

    /** Backdrop / Cancel — respect in-flight ``busy`` (save/delete/clear). */
    closeClearMessagesModal() {
      if (!opts.isBusy()) clearMessagesConfirmOpen = false;
    },

    /** Server clear succeeded; always close even when ``busy`` was true mid-request. */
    closeClearMessagesAfterSuccess() {
      clearMessagesConfirmOpen = false;
    },

    closeDeleteModal() {
      if (!opts.isBusy()) deleteTarget = null;
    },

    clearDeleteTarget() {
      deleteTarget = null;
    },

    openDiscardConfirmModal() {
      discardConfirmOpen = true;
    },

    closeDiscardConfirmModal() {
      discardConfirmOpen = false;
    }
  };
}
