import { browser } from '$app/environment';
import { PREF_KEYS } from '$lib/preferences/keys';

/**
 * Per-surface chat composer/bubble UI toggles, persisted to localStorage.
 *
 * These are local UX preferences (not URL/tab state — that lives in
 * `createChatChannelsPreferences`). Encoded as `'1'`/`'0'` to match the values
 * the chat engine has always written, so existing toggles survive this refactor.
 *
 * Read at construction: the chat engine is a client-side singleton created inside
 * `AdminShell`, so `browser` is true by the time this runs; the SSR instance reads
 * defaults and is discarded before hydration.
 */
type ChatUiPrefKey =
  | typeof PREF_KEYS.chatChannelsVoiceReply
  | typeof PREF_KEYS.chatChannelsUseKnowledge
  | typeof PREF_KEYS.chatChannelsDisableTools
  | typeof PREF_KEYS.chatChannelsShowAgentTelemetry
  | typeof PREF_KEYS.chatChannelsShowAgentTools;

function readBool(key: ChatUiPrefKey, fallback: boolean): boolean {
  if (!browser) return fallback;
  const raw = localStorage.getItem(key);
  if (raw === '1') return true;
  if (raw === '0') return false;
  return fallback;
}

function persistBool(key: ChatUiPrefKey, value: boolean) {
  if (!browser) return;
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    /* ignore quota / private mode */
  }
}

export type ChatChannelsUiPrefs = ReturnType<typeof createChatChannelsUiPrefs>;

export function createChatChannelsUiPrefs() {
  /** "Ask for voice reply" — opt-in, off by default. */
  let requestVoiceReply = $state(readBool(PREF_KEYS.chatChannelsVoiceReply, false));
  /** "Use knowledge" per-message augmentation — on by default. */
  let useKnowledge = $state(readBool(PREF_KEYS.chatChannelsUseKnowledge, true));
  /** "Disable tools" per-message override — off by default (⇒ tools on). */
  let disableTools = $state(readBool(PREF_KEYS.chatChannelsDisableTools, false));
  /** Token/cost stats on Messages bubbles — on by default. */
  let showAgentTokens = $state(readBool(PREF_KEYS.chatChannelsShowAgentTelemetry, true));
  /** Agent tool stack on Messages bubbles — on by default. */
  let showAgentTools = $state(readBool(PREF_KEYS.chatChannelsShowAgentTools, true));

  return {
    get requestVoiceReply() {
      return requestVoiceReply;
    },
    set requestVoiceReply(v: boolean) {
      requestVoiceReply = v;
      persistBool(PREF_KEYS.chatChannelsVoiceReply, v);
    },
    get useKnowledge() {
      return useKnowledge;
    },
    set useKnowledge(v: boolean) {
      useKnowledge = v;
      persistBool(PREF_KEYS.chatChannelsUseKnowledge, v);
    },
    get disableTools() {
      return disableTools;
    },
    set disableTools(v: boolean) {
      disableTools = v;
      persistBool(PREF_KEYS.chatChannelsDisableTools, v);
    },
    get showAgentTokens() {
      return showAgentTokens;
    },
    set showAgentTokens(v: boolean) {
      showAgentTokens = v;
      persistBool(PREF_KEYS.chatChannelsShowAgentTelemetry, v);
    },
    get showAgentTools() {
      return showAgentTools;
    },
    set showAgentTools(v: boolean) {
      showAgentTools = v;
      persistBool(PREF_KEYS.chatChannelsShowAgentTools, v);
    },

    /**
     * Force the voice-reply checkbox visually off (selected character can't do
     * voice) WITHOUT persisting, so the user's saved preference is restored when
     * they return to a voice-capable character. Mirrors the pre-refactor in-memory
     * reset that bypassed localStorage.
     */
    clearVoiceReplyTransient() {
      requestVoiceReply = false;
    }
  };
}
