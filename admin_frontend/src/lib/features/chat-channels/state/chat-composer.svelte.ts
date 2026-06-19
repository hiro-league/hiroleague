import { sendChatMessage } from '$lib/api/chat-channels';
import type { ToastKind } from '$lib/ui/toast-types';
import { pickRecordingMimeType } from '$lib/features/chat-channels/shared/chat-channel-media';
import {
  buildRecordingBlobFromChunks,
  recordingBlobToBase64,
  stopMediaRecorderAndDetach
} from '$lib/features/chat-channels/shared/chat-channel-recording';
import type { ChatMessagesEngine } from '$lib/features/chat-channels/state/chat-messages-engine.svelte';
import type { ChatChannelsUiPrefs } from '$lib/features/chat-channels/state/chat-channels-ui-prefs.svelte';

type ChatComposerOptions = {
  getSelectedChannelId: () => string | null;
  engine: ChatMessagesEngine;
  uiPrefs: ChatChannelsUiPrefs;
  /** Whether a voice reply should be requested for this send (character-gated). */
  effectiveRequestVoiceReply: () => boolean;
  notify: (kind: ToastKind, message: string) => void;
};

/**
 * Message composer: the draft text box plus microphone capture and the text/voice
 * send flow (optimistic echo + agent-reply arming via the message engine). Owns its
 * own busy/recording state; reads the selected channel back from the parent controller.
 */
export function createChatComposer(opts: ChatComposerOptions) {
  const { getSelectedChannelId, engine, uiPrefs, effectiveRequestVoiceReply, notify } = opts;

  let draftMessage = $state('');
  let recordingStartedAt = $state<number | null>(null);
  let composingBusy = $state(false);

  let mediaRecorderObj: MediaRecorder | null = null;
  let recordingChunks: Blob[] = [];

  async function submitDraftText() {
    const id = getSelectedChannelId() ? Number(getSelectedChannelId()) : NaN;
    const text = draftMessage.trim();
    if (!Number.isFinite(id) || !text) return;
    composingBusy = true;
    try {
      const requestVoiceReply = effectiveRequestVoiceReply();
      const sent = await sendChatMessage(id, {
        text,
        request_voice_reply: requestVoiceReply || undefined,
        use_knowledge: uiPrefs.useKnowledge,
        disable_tools: uiPrefs.disableTools || undefined
      });
      const sentAt = new Date().toISOString();
      draftMessage = '';
      engine.addOptimisticMessage({
        id: sent.data.message_id,
        message_pk: engine.nextOptimisticPk(),
        channel_id: id,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: sentAt,
        content: [{ content_type: 'text', body: text }]
      });
      engine.markAgentReplyPending(sentAt, requestVoiceReply);
      notify('success', 'Message sent.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Send failed.');
    } finally {
      composingBusy = false;
    }
  }

  async function beginRecording() {
    const channelId = getSelectedChannelId();
    if (!channelId || recordingStartedAt !== null) return;
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      notify('error', 'Microphone recording is unavailable in this browser.');
      return;
    }
    const id = Number(channelId);
    if (!Number.isFinite(id)) return;
    composingBusy = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickRecordingMimeType();
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      recordingChunks = [];
      mr.ondataavailable = (ev: BlobEvent) => {
        if (ev.data && ev.data.size > 0) recordingChunks.push(ev.data);
      };
      mr.start(250);
      mediaRecorderObj = mr;
      recordingStartedAt = performance.now();
    } catch (err) {
      recordingStartedAt = null;
      mediaRecorderObj = null;
      notify('error', err instanceof Error ? err.message : 'Could not start microphone.');
    } finally {
      composingBusy = false;
    }
  }

  async function finalizeRecording() {
    if (!mediaRecorderObj || recordingStartedAt === null) return;
    const mr = mediaRecorderObj;
    const started = recordingStartedAt;
    const id = Number(getSelectedChannelId());
    const chunkSnapshot = recordingChunks.slice();

    recordingStartedAt = null;
    mediaRecorderObj = null;

    await stopMediaRecorderAndDetach(mr);
    recordingChunks = [];

    composingBusy = true;
    try {
      const { blob, effectiveMime } = buildRecordingBlobFromChunks(chunkSnapshot, mr.mimeType);
      const duration_ms = Math.max(1, Math.round(performance.now() - started));
      const b64 = await recordingBlobToBase64(blob);
      const requestVoiceReply = effectiveRequestVoiceReply();
      const sent = await sendChatMessage(id, {
        audio_base64: b64,
        audio_mime_type: effectiveMime,
        audio_duration_ms: duration_ms,
        request_voice_reply: requestVoiceReply || undefined,
        use_knowledge: uiPrefs.useKnowledge,
        disable_tools: uiPrefs.disableTools || undefined
      });
      const sentAt = new Date().toISOString();
      engine.addOptimisticMessage({
        id: sent.data.message_id,
        message_pk: engine.nextOptimisticPk(),
        channel_id: id,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: sentAt,
        content: [
          {
            content_type: 'audio',
            body: `optimistic_audio:${sent.data.message_id}`,
            metadata: {
              duration_ms,
              media_type: effectiveMime,
              optimistic_audio_url: URL.createObjectURL(blob)
            }
          }
        ]
      });
      engine.markAgentReplyPending(sentAt, requestVoiceReply);
      notify('success', 'Voice message sent.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Send failed.');
    } finally {
      composingBusy = false;
    }
  }

  async function discardRecording() {
    if (!mediaRecorderObj || recordingStartedAt === null) return;
    const mr = mediaRecorderObj;
    recordingStartedAt = null;
    mediaRecorderObj = null;
    recordingChunks = [];
    await stopMediaRecorderAndDetach(mr);
  }

  /**
   * Stop capture without sending — e.g. user navigates away while recording (avoids orphaned
   * MediaStream tracks). Fire-and-forget from ``onMount`` cleanup is OK; we still await stop so
   * the browser can release the mic.
   */
  async function disposeActiveRecording() {
    const mr = mediaRecorderObj;
    recordingStartedAt = null;
    mediaRecorderObj = null;
    recordingChunks = [];
    if (!mr) return;
    await stopMediaRecorderAndDetach(mr);
  }

  return {
    submitDraftText,
    beginRecording,
    finalizeRecording,
    discardRecording,
    disposeActiveRecording,

    get draftMessage(): string {
      return draftMessage;
    },
    set draftMessage(v: string) {
      draftMessage = v;
    },
    get recordingStartedAt(): number | null {
      return recordingStartedAt;
    },
    get composingBusy(): boolean {
      return composingBusy;
    }
  };
}
