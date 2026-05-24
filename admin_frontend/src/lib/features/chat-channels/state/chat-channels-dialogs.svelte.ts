import type { ChatChannelRow } from '$lib/api/chat-channels';

/**
 * Confirm / destructive modal flags for chat channels (clear thread, delete channel).
 * Unsaved editor changes use the shared `createUnsavedGuard` in the page controller.
 */
export function createChatChannelsDialogs(opts: { isBusy: () => boolean }) {
  let clearMessagesConfirmOpen = $state(false);
  let deleteTarget = $state<ChatChannelRow | null>(null);

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
    }
  };
}
