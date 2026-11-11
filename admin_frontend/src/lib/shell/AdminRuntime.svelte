<script lang="ts">
  // What runs for as long as someone is signed in to the admin, whatever page shows, inside the shared shell
  // (@hiroleague/ui's app-shell, its `overlays`): the live status stream, the watch on the server being up, the
  // chat engine, and what floats over every page (the chat, its toasts and its clear-messages dialog).
  // UI kit step 2b: this was the script and the tail of AdminShell.
  import { onMount } from 'svelte';
  import GlobalChatOverlay from '$lib/features/chat-channels/overlay/GlobalChatOverlay.svelte';
  import ChatChannelClearMessagesModal from '$lib/features/chat-channels/modals/ChatChannelClearMessagesModal.svelte';
  import { getChatEngine } from '$lib/features/chat-channels/state/chat-engine-singleton.svelte';
  import { liveStatus } from '$lib/live/status.svelte';
  import { createShellPreferences } from '$lib/preferences/shell-preferences.svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import { toast } from '$kit/ui/toast.svelte';

  const prefs = createShellPreferences();
  // Create the shared chat engine here, in the always-mounted part of the shell, so it owns the controller's
  // $effect/$derived for the whole session. The /chats page and the global overlay reuse this exact instance
  // via getChatEngine().
  const chatEngine = getChatEngine();
  /** Tracks SSE connect/disconnect so we can nudge the readiness poller on drop. */
  let liveWasConnected = false;

  // UI kit, step 3: the admin's toasts are the kit's one toast now (pages had one each). The banner owns the
  // "server is starting" message, so error toasts wait until the server is up.
  toast.quiet = (kind) => kind === 'error' && !serverReadiness.ready;

  onMount(() => {
    prefs.initialize();
    liveStatus.start(prefs.selectedWorkspace);
    serverReadiness.subscribe();
  });

  $effect(() => {
    const connected = liveStatus.connected;
    // Only treat an SSE drop as a possible outage when the tab is visible. A hidden tab
    // deliberately closes its stream (see the status store's visibilitychange handler),
    // which is not a server drop — marking stale there would spuriously poll while
    // backgrounded and flash the "Server unavailable" banner on refocus.
    const visible = typeof document === 'undefined' || document.visibilityState === 'visible';
    if (liveWasConnected && !connected && visible) {
      serverReadiness.markStale();
    }
    liveWasConnected = connected;
  });
</script>

<!-- Global chat: floating overlay + the shared engine's clear-messages modal.
     These live in the shell (not the /chats page) so they work over any page. -->
<GlobalChatOverlay />

<ChatChannelClearMessagesModal
  open={chatEngine.clearMessagesConfirmOpen}
  channelName={chatEngine.clearMessagesChannelDisplayName}
  busy={chatEngine.busy}
  onClose={() => chatEngine.closeClearMessagesModal()}
  onConfirm={() => void chatEngine.submitClearMessages()}
/>
