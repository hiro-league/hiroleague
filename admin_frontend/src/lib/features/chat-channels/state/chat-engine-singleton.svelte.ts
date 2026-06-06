import {
  createChatChannelsPageController,
  type ChatChannelsPageController
} from '$lib/features/chat-channels/state/chat-channels-controller.svelte';

/**
 * Single shared chat conversation engine.
 *
 * One live conversation observed from multiple surfaces: the /chats Messages tab
 * and the global chat overlay both bind THIS instance, so they always reflect the
 * same selected channel, messages, typing/stats, and a single polling/streaming
 * loop (no duplicated comms). Future observers (graph-run ledger, execution log)
 * read the same engine — added, not diverted.
 *
 * IMPORTANT: the controller uses `$state`/`$derived`/`$effect`, so it must be
 * created inside a long-lived component's reactive context. `AdminShell` (the app
 * shell, mounted for the whole session) calls `getChatEngine()` first and thus
 * owns the engine's effects; every other caller reuses the same instance.
 */
let engine: ChatChannelsPageController | null = null;

export function getChatEngine(): ChatChannelsPageController {
  if (!engine) {
    engine = createChatChannelsPageController();
  }
  return engine;
}
