import { PREF_KEYS } from '$lib/preferences/keys';
import { boolCodec } from '$lib/state/codecs';
import { createPersistentState } from '$lib/state/create-persistent-state.svelte';

/**
 * Per-surface chat composer/bubble UI toggles, persisted to localStorage.
 *
 * Each field uses `boolCodec(..., 'bool01')` so stored values stay `'1'`/`'0'`
 * (same keys the chat engine has always written).
 */
export type ChatChannelsUiPrefs = ReturnType<typeof createChatChannelsUiPrefs>;

export function createChatChannelsUiPrefs() {
  const requestVoiceReplyState = createPersistentState({
    key: PREF_KEYS.chatChannelsVoiceReply,
    tier: 'local',
    codec: boolCodec(false, 'bool01')
  });
  const useKnowledgeState = createPersistentState({
    key: PREF_KEYS.chatChannelsUseKnowledge,
    tier: 'local',
    codec: boolCodec(true, 'bool01')
  });
  const disableToolsState = createPersistentState({
    key: PREF_KEYS.chatChannelsDisableTools,
    tier: 'local',
    codec: boolCodec(false, 'bool01')
  });
  const showAgentTokensState = createPersistentState({
    key: PREF_KEYS.chatChannelsShowAgentTelemetry,
    tier: 'local',
    codec: boolCodec(true, 'bool01')
  });
  const showAgentToolsState = createPersistentState({
    key: PREF_KEYS.chatChannelsShowAgentTools,
    tier: 'local',
    codec: boolCodec(true, 'bool01')
  });

  /** When set, overrides voice-reply display without persisting (non-voice character selected). */
  let voiceReplyTransientOff = $state(false);

  return {
    get requestVoiceReply() {
      return voiceReplyTransientOff ? false : requestVoiceReplyState.value;
    },
    set requestVoiceReply(v: boolean) {
      voiceReplyTransientOff = false;
      requestVoiceReplyState.value = v;
    },
    get useKnowledge() {
      return useKnowledgeState.value;
    },
    set useKnowledge(v: boolean) {
      useKnowledgeState.value = v;
    },
    get disableTools() {
      return disableToolsState.value;
    },
    set disableTools(v: boolean) {
      disableToolsState.value = v;
    },
    get showAgentTokens() {
      return showAgentTokensState.value;
    },
    set showAgentTokens(v: boolean) {
      showAgentTokensState.value = v;
    },
    get showAgentTools() {
      return showAgentToolsState.value;
    },
    set showAgentTools(v: boolean) {
      showAgentToolsState.value = v;
    },

    clearVoiceReplyTransient() {
      voiceReplyTransientOff = true;
    }
  };
}
