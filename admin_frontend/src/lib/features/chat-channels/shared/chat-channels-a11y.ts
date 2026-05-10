/** Stable DOM ids for tablist / tabpanel wiring (avoid aria-controls → missing nodes). */

export const CHAT_CHANNELS_TABLIST_LABEL = 'Chat channel sections';

export const CHAT_CHANNELS_TAB_IDS = {
  channels: 'chat-channels-tab-channels',
  messages: 'chat-channels-tab-messages'
} as const;

export const CHAT_CHANNELS_PANEL_IDS = {
  channels: 'chat-channels-panel-channels',
  messages: 'chat-channels-panel-messages'
} as const;
