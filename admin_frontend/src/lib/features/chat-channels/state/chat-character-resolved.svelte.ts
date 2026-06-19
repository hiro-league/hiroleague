import { getCharacterResolved, type CharacterResolvedPayload } from '$lib/api/characters';
import type { ChatChannelRow } from '$lib/api/chat-channels';
import {
  characterResolvedAllowsVoiceRequest,
  characterResolvedVoiceReplyControlHint
} from '$lib/features/characters/shared/character-resolved-voice';
import type { ChatChannelsUiPrefs } from '$lib/features/chat-channels/state/chat-channels-ui-prefs.svelte';

type ChatCharacterResolvedOptions = {
  /** The currently selected channel (owned by the parent controller) — its character drives TTS. */
  getSelectedChannel: () => ChatChannelRow | null;
  /** UI prefs — voice-reply gate + transient reset when the character can't do voice. */
  uiPrefs: ChatChannelsUiPrefs;
};

/**
 * Resolved TTS configuration for the selected channel's character (mirrors the
 * Characters page voice block). Owns its own fetch sequencing so stale responses
 * never clobber a newer channel selection, and gates the "Get voice reply" toggle.
 */
export function createChatCharacterResolved(opts: ChatCharacterResolvedOptions) {
  const { getSelectedChannel, uiPrefs } = opts;

  let payload = $state<CharacterResolvedPayload | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let fetchSeq = 0;

  function clear() {
    payload = null;
    error = null;
    loading = false;
  }

  /** Load resolved config for the selected channel's character; no-op (cleared) when none. */
  async function refresh() {
    const ch = getSelectedChannel();
    if (!ch?.character_id?.trim()) {
      clear();
      return;
    }
    const cid = ch.character_id.trim();
    const seq = ++fetchSeq;
    loading = true;
    error = null;
    try {
      const res = await getCharacterResolved(cid);
      if (seq !== fetchSeq) return;
      payload = res.data;
      error = null;
      if (!characterResolvedAllowsVoiceRequest(res.data)) {
        uiPrefs.clearVoiceReplyTransient();
      }
    } catch (e) {
      if (seq !== fetchSeq) return;
      payload = null;
      error = e instanceof Error ? e.message : 'Request failed.';
      uiPrefs.clearVoiceReplyTransient();
    } finally {
      if (seq === fetchSeq) loading = false;
    }
  }

  /** Whether to actually request a voice reply on send: character allows it AND the user opted in. */
  function effectiveRequestVoiceReply(): boolean {
    return characterResolvedAllowsVoiceRequest(payload) && uiPrefs.requestVoiceReply;
  }

  return {
    clear,
    refresh,
    effectiveRequestVoiceReply,

    get voiceReplyCheckboxDisabled(): boolean {
      return loading || !characterResolvedAllowsVoiceRequest(payload);
    },
    get voiceReplyCheckboxHint(): string {
      return characterResolvedVoiceReplyControlHint(payload, error, loading);
    }
  };
}
