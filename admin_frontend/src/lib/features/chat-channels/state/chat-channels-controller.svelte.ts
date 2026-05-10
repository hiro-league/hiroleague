import { page } from '$app/state';
import {
  clearChatMessages,
  createChatChannel,
  deleteChatChannel,
  listChatChannels,
  listChatMessages,
  sendChatMessage,
  updateChatChannel,
  uploadChatChannelPhoto,
  type ChatChannelRow,
  type ChatHistoryMessage
} from '$lib/api/chat-channels';
import { getCharacterResolved, listCharacters, type CharacterResolvedPayload, type CharacterRow } from '$lib/api/characters';
import {
  isChatChannelFormDirty,
  parseChatChannelFormForSave,
  snapshotChatChannelFormBaseline,
  type ChatChannelFormBaseline,
  type ChatChannelFormFields
} from '$lib/features/chat-channels/shared/chat-channel-form';
import { pickRecordingMimeType } from '$lib/features/chat-channels/shared/chat-channel-media';
import {
  buildRecordingBlobFromChunks,
  recordingBlobToBase64,
  stopMediaRecorderAndDetach
} from '$lib/features/chat-channels/shared/chat-channel-recording';
import {
  readChatChannelsNavFromLocation,
  persistChatChannelsNavToUrl
} from '$lib/features/chat-channels/state/chat-channels-nav';
import { createChatChannelsDialogs } from '$lib/features/chat-channels/state/chat-channels-dialogs.svelte';
import { PREF_KEYS, type ChatChannelsTabPreference } from '$lib/preferences/keys';
import {
  characterResolvedAllowsVoiceRequest,
  characterResolvedVoiceReplyControlHint
} from '$lib/features/characters/character-resolved-voice';

type NotifyKind = 'success' | 'error' | 'info' | 'warning';

/** Chat channels Messages tab orchestration — URL prefs, REST, mic capture, modal wiring. Derived fields use getters per Svelte POJO-controller pattern. */
export function createChatChannelsPageController() {
  let toast = $state<{ kind: NotifyKind; message: string } | null>(null);
  let activeTab = $state<ChatChannelsTabPreference>('channels');
  let selectedChannelId = $state<string | null>(null);
  let channels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);
  let messages = $state<ChatHistoryMessage[]>([]);
  let channelsLoading = $state(true);
  let messagesLoading = $state(false);
  let channelsError = $state<string | null>(null);
  let messagesError = $state<string | null>(null);
  let busy = $state(false);
  /** Confirm/delete/discard overlay flags live here so destructive UX rules stay centralized. */
  const dlg = createChatChannelsDialogs({ isBusy: () => busy });
  let formOpen = $state(false);
  let formMode = $state<'create' | 'edit'>('create');
  let editingChannelId = $state<number | null>(null);
  let formError = $state<string | null>(null);
  let form = $state<ChatChannelFormFields>({ name: '', characterId: '', description: '' });
  let pendingPhotoDataUrl = $state<string | null>(null);
  let formBaseline = $state<ChatChannelFormBaseline | null>(null);
  let requestVoiceReplyUi = $state(false);
  let draftMessage = $state('');
  let recordingStartedAt = $state<number | null>(null);
  let composingBusy = $state(false);

  /** ``GET /characters/:id/resolved`` for the selected channel’s character — same basis as the Characters page voice block. */
  let characterResolvedForMessages = $state<CharacterResolvedPayload | null>(null);
  let characterResolvedLoading = $state(false);
  let characterResolvedError = $state<string | null>(null);
  let characterResolvedFetchSeq = 0;

  let mediaRecorderObj: MediaRecorder | null = null;
  let recordingChunks: Blob[] = [];

  const channelFormDirty = $derived(
    isChatChannelFormDirty({
      formOpen,
      baseline: formBaseline,
      form,
      pendingPhotoDataUrl
    })
  );

  const selectedChannel = $derived(
    selectedChannelId
      ? (channels.find((channel) => String(channel.id) === selectedChannelId) ?? null)
      : null
  );

  const messagesHeaderPhotoSrc = $derived.by(() => {
    const ch = selectedChannel;
    if (!ch) return null;
    const row = characters.find((c) => c.id === ch.character_id);
    return row?.photo_data_url ?? ch.photo_data_url ?? null;
  });

  const messagesHeaderCharacterName = $derived.by(() => {
    const ch = selectedChannel;
    if (!ch) return null;
    const row = characters.find((c) => c.id === ch.character_id);
    return row?.name ?? ch.character?.name ?? ch.character_id;
  });

  const messagesHeaderDeviceId = $derived.by(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m?.sender_type === 'user') {
        const id = (m.sender_id ?? '').trim();
        if (id) return id;
      }
    }
    return null as string | null;
  });

  const messagesHeaderChannelHint = $derived.by(() =>
    selectedChannel ? `${selectedChannel.name} · id ${selectedChannel.id}` : ''
  );

  const formTitle = $derived(
    formMode === 'create' ? 'New conversation channel' : 'Edit conversation channel'
  );

  const modalChannelPhotoSrc = $derived(
    pendingPhotoDataUrl ??
      (formMode === 'edit' && editingChannelId !== null
        ? (channels.find((c) => c.id === editingChannelId)?.photo_data_url ?? null)
        : null)
  );

  function notify(kind: NotifyKind, message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  /** Restore tab/channel from ``readChatChannelsNavFromLocation``. */
  function initializeNavigation() {
    const { tab, channelId } = readChatChannelsNavFromLocation(page.url.searchParams);
    activeTab = tab;
    selectedChannelId = channelId;
  }

  async function syncUrl() {
    await persistChatChannelsNavToUrl(page.url, activeTab, selectedChannelId);
  }

  function ensureSelectedChannel(): string | null {
    if (selectedChannelId && channels.some((channel) => String(channel.id) === selectedChannelId)) {
      return selectedChannelId;
    }
    selectedChannelId = channels.length > 0 ? String(channels[0].id) : null;
    return selectedChannelId;
  }

  function clearCharacterResolvedForMessages() {
    characterResolvedForMessages = null;
    characterResolvedError = null;
    characterResolvedLoading = false;
  }

  /** Loads resolved TTS configuration for ``selectedChannel`` (admin Phase 7 — mirrors Characters page). */
  async function refreshCharacterResolvedForMessagesChannel() {
    const ch = selectedChannel;
    if (!ch?.character_id?.trim()) {
      clearCharacterResolvedForMessages();
      return;
    }
    const cid = ch.character_id.trim();
    const seq = ++characterResolvedFetchSeq;
    characterResolvedLoading = true;
    characterResolvedError = null;
    try {
      const payload = await getCharacterResolved(cid);
      if (seq !== characterResolvedFetchSeq) return;
      characterResolvedForMessages = payload.data;
      characterResolvedError = null;
      if (!characterResolvedAllowsVoiceRequest(payload.data)) {
        requestVoiceReplyUi = false;
      }
    } catch (e) {
      if (seq !== characterResolvedFetchSeq) return;
      characterResolvedForMessages = null;
      characterResolvedError = e instanceof Error ? e.message : 'Request failed.';
      requestVoiceReplyUi = false;
    } finally {
      if (seq === characterResolvedFetchSeq) characterResolvedLoading = false;
    }
  }

  function effectiveRequestVoiceReplyForSend(): boolean {
    return (
      characterResolvedAllowsVoiceRequest(characterResolvedForMessages) && requestVoiceReplyUi
    );
  }

  async function loadCharacters() {
    try {
      const payload = await listCharacters();
      characters = payload.data;
    } catch {
      characters = [];
    }
  }

  async function loadChannels() {
    channelsLoading = true;
    channelsError = null;
    try {
      const payload = await listChatChannels();
      channels = payload.data;
      if (selectedChannelId && !channels.some((channel) => String(channel.id) === selectedChannelId)) {
        selectedChannelId = null;
      }
    } catch (err) {
      channelsError = err instanceof Error ? err.message : 'Failed to load chat channels.';
    } finally {
      channelsLoading = false;
    }
  }

  async function loadMessages() {
    const channelId = ensureSelectedChannel();
    if (!channelId) {
      messages = [];
      messagesError = null;
      clearCharacterResolvedForMessages();
      return;
    }

    messagesLoading = true;
    messagesError = null;
    try {
      const payload = await listChatMessages(Number(channelId));
      messages = payload.data;
    } catch (err) {
      messagesError = err instanceof Error ? err.message : 'Failed to load messages.';
    } finally {
      messagesLoading = false;
      void refreshCharacterResolvedForMessagesChannel();
    }
  }

  async function refreshCurrent() {
    await loadChannels();
    if (activeTab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
    }
  }

  async function setActiveTab(tab: ChatChannelsTabPreference) {
    activeTab = tab;
    if (tab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
      return;
    }
    await syncUrl();
  }

  async function openMessages(row: ChatChannelRow) {
    activeTab = 'messages';
    selectedChannelId = String(row.id);
    await syncUrl();
    await loadMessages();
  }

  async function handleChannelSelect() {
    await syncUrl();
    await loadMessages();
  }

  function characterLabel(id: string) {
    const row = characters.find((c) => c.id === id);
    return row ? `${row.name} — ${row.id}` : id;
  }

  function openCreate() {
    formMode = 'create';
    editingChannelId = null;
    formError = null;
    pendingPhotoDataUrl = null;
    form = { name: '', characterId: characters[0]?.id ?? '', description: '' };
    formBaseline = snapshotChatChannelFormBaseline(form, pendingPhotoDataUrl);
    formOpen = true;
  }

  function openEdit(row: ChatChannelRow) {
    formMode = 'edit';
    editingChannelId = row.id;
    formError = null;
    pendingPhotoDataUrl = null;
    form = {
      name: row.name,
      characterId: row.character_id,
      description: row.description ?? ''
    };
    formBaseline = snapshotChatChannelFormBaseline(form, pendingPhotoDataUrl);
    formOpen = true;
  }

  /** Stack discard modal above editor when closing with dirty form. */
  function channelFormBeforeClose(_source: 'backdrop' | 'escape' | 'header'): boolean {
    void _source;
    if (dlg.discardConfirmOpen) return false;
    if (!channelFormDirty) return true;
    dlg.openDiscardConfirmModal();
    return false;
  }

  function finalizeChannelForm() {
    formOpen = false;
    dlg.closeDiscardConfirmModal();
    formBaseline = null;
    pendingPhotoDataUrl = null;
  }

  function cancelChannelFormExplicit() {
    if (busy) return;
    finalizeChannelForm();
  }

  function keepEditingAfterDismissAttempt() {
    dlg.closeDiscardConfirmModal();
  }

  function discardUnsavedChannelFormAndClose() {
    dlg.closeDiscardConfirmModal();
    finalizeChannelForm();
  }

  async function submitForm() {
    const parsed = parseChatChannelFormForSave(form);
    if (!parsed.ok) {
      formError = parsed.error;
      return;
    }
    formError = null;
    const payload = parsed.payload;

    busy = true;
    try {
      let channelIdSaved: number;
      if (formMode === 'edit' && editingChannelId !== null) {
        await updateChatChannel(editingChannelId, payload);
        channelIdSaved = editingChannelId;
        notify('success', 'Channel updated.');
      } else {
        const res = await createChatChannel(payload);
        channelIdSaved = res.data.id;
        notify('success', 'Channel created.');
      }
      if (pendingPhotoDataUrl) {
        await uploadChatChannelPhoto(channelIdSaved, pendingPhotoDataUrl);
        pendingPhotoDataUrl = null;
      }
      finalizeChannelForm();
      await refreshCurrent();
    } catch (err) {
      formError = err instanceof Error ? err.message : 'Save failed.';
    } finally {
      busy = false;
    }
  }

  function closeDelete() {
    dlg.closeDeleteModal();
  }

  async function submitDelete() {
    const target = dlg.deleteTarget;
    if (!target) return;

    busy = true;
    try {
      const deletedId = target.id;
      await deleteChatChannel(deletedId);
      notify('success', 'Channel deleted.');
      dlg.clearDeleteTarget();
      if (selectedChannelId === String(deletedId)) {
        selectedChannelId = null;
        messages = [];
      }
      await refreshCurrent();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Delete failed.');
    } finally {
      busy = false;
    }
  }

  function closeClearMessagesModal() {
    dlg.closeClearMessagesModal();
  }

  async function submitClearMessages() {
    const id = selectedChannelId ? Number(selectedChannelId) : NaN;
    if (!Number.isFinite(id)) return;

    busy = true;
    try {
      await clearChatMessages(id);
      dlg.closeClearMessagesAfterSuccess();
      notify('success', 'All messages were cleared.');
      await loadChannels();
      await loadMessages();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to clear messages.');
    } finally {
      busy = false;
    }
  }

  async function submitDraftText() {
    const id = selectedChannelId ? Number(selectedChannelId) : NaN;
    const text = draftMessage.trim();
    if (!Number.isFinite(id) || !text) return;
    composingBusy = true;
    try {
      await sendChatMessage(id, {
        text,
        request_voice_reply: effectiveRequestVoiceReplyForSend() || undefined
      });
      draftMessage = '';
      notify('success', 'Message sent.');
      await loadMessages();
      await loadChannels();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Send failed.');
    } finally {
      composingBusy = false;
    }
  }

  async function beginRecording() {
    if (!selectedChannelId || recordingStartedAt !== null) return;
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      notify('error', 'Microphone recording is unavailable in this browser.');
      return;
    }
    const id = Number(selectedChannelId);
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
    const id = Number(selectedChannelId);
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
      await sendChatMessage(id, {
        audio_base64: b64,
        audio_mime_type: effectiveMime,
        audio_duration_ms: duration_ms,
        request_voice_reply: effectiveRequestVoiceReplyForSend() || undefined
      });
      notify('success', 'Voice message sent.');
      await loadMessages();
      await loadChannels();
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
   * Stop capture without sending — e.g. user navigates away while recording (avoids orphaned MediaStream tracks).
   * Fire-and-forget from ``onMount`` cleanup is OK; we still await stop so the browser can release the mic.
   */
  async function disposeActiveRecording() {
    const mr = mediaRecorderObj;
    recordingStartedAt = null;
    mediaRecorderObj = null;
    recordingChunks = [];
    if (!mr) return;
    await stopMediaRecorderAndDetach(mr);
  }

  async function mount() {
    try {
      const raw = localStorage.getItem(PREF_KEYS.chatChannelsVoiceReply);
      if (raw === '1') requestVoiceReplyUi = true;
      if (raw === '0') requestVoiceReplyUi = false;
    } catch {
      /* ignore quota / private mode */
    }
    initializeNavigation();
    await loadCharacters();
    await loadChannels();
    if (activeTab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
    }
  }

  return {
    mount,

    loadChannels,
    refreshCurrent,
    setActiveTab,

    openMessages,
    handleChannelSelect,

    characterLabel,
    openCreate,
    openEdit,

    channelFormBeforeClose,
    finalizeChannelForm,
    cancelChannelFormExplicit,
    keepEditingAfterDismissAttempt,
    discardUnsavedChannelFormAndClose,

    submitForm,

    closeDelete,

    openClearMessagesModal: dlg.openClearMessagesModal,
    closeClearMessagesModal,
    submitDelete,
    submitClearMessages,

    submitDraftText,
    beginRecording,
    finalizeRecording,
    discardRecording,
    disposeActiveRecording,

    get toast() {
      return toast;
    },
    get activeTab() {
      return activeTab;
    },

    /** Messages panel two-way binds read/write `$state` in this controller via getters/setters. */
    get selectedChannelId() {
      return selectedChannelId;
    },
    set selectedChannelId(v: string | null) {
      selectedChannelId = v;
    },
    get requestVoiceReplyUi() {
      return requestVoiceReplyUi;
    },
    set requestVoiceReplyUi(v: boolean) {
      requestVoiceReplyUi = v;
      try {
        localStorage.setItem(PREF_KEYS.chatChannelsVoiceReply, v ? '1' : '0');
      } catch {
        /* ignore */
      }
    },
    get draftMessage() {
      return draftMessage;
    },
    set draftMessage(v: string) {
      draftMessage = v;
    },

    get channels(): ChatChannelRow[] {
      return channels;
    },
    get channelsLoading(): boolean {
      return channelsLoading;
    },
    get channelsError(): string | null {
      return channelsError;
    },
    get messages(): ChatHistoryMessage[] {
      return messages;
    },
    get messagesLoading(): boolean {
      return messagesLoading;
    },
    get messagesError(): string | null {
      return messagesError;
    },
    get busy(): boolean {
      return busy;
    },
    get formOpen(): boolean {
      return formOpen;
    },

    get deleteTarget(): ChatChannelRow | null {
      return dlg.deleteTarget;
    },
    set deleteTarget(v: ChatChannelRow | null) {
      dlg.deleteTarget = v;
    },

    get clearMessagesConfirmOpen(): boolean {
      return dlg.clearMessagesConfirmOpen;
    },

    /** ``Clear messages`` confirmation copy matches previous ``selectedChannel?.name`` fallback. */
    get clearMessagesChannelDisplayName(): string {
      const ch = selectedChannel;
      return ch?.name ?? 'this channel';
    },

    get recordingStartedAt(): number | null {
      return recordingStartedAt;
    },
    get composingBusy(): boolean {
      return composingBusy;
    },

    get discardConfirmOpen(): boolean {
      return dlg.discardConfirmOpen;
    },

    get modalChannelPhotoSrc(): string | null {
      return modalChannelPhotoSrc;
    },
    get formTitle(): string {
      return formTitle;
    },
    get formMode(): 'create' | 'edit' {
      return formMode;
    },
    get form(): ChatChannelFormFields {
      return form;
    },
    set form(v: ChatChannelFormFields) {
      form = v;
    },
    get pendingPhotoDataUrl(): string | null {
      return pendingPhotoDataUrl;
    },
    set pendingPhotoDataUrl(v: string | null) {
      pendingPhotoDataUrl = v;
    },
    get formError(): string | null {
      return formError;
    },
    get characters(): CharacterRow[] {
      return characters;
    },

    get selectedChannelExists(): boolean {
      return selectedChannel !== null;
    },
    get messagesHeaderPhotoSrc(): string | null {
      return messagesHeaderPhotoSrc;
    },
    get messagesHeaderChannelHint(): string {
      return messagesHeaderChannelHint;
    },
    get messagesHeaderCharacterName(): string | null {
      return messagesHeaderCharacterName;
    },
    get messagesHeaderDeviceId(): string | null {
      return messagesHeaderDeviceId;
    },

    get voiceReplyCheckboxDisabled(): boolean {
      return (
        characterResolvedLoading ||
        !characterResolvedAllowsVoiceRequest(characterResolvedForMessages)
      );
    },
    get voiceReplyCheckboxHint(): string {
      return characterResolvedVoiceReplyControlHint(
        characterResolvedForMessages,
        characterResolvedError,
        characterResolvedLoading
      );
    },

    get channelFormDirty(): boolean {
      return channelFormDirty;
    }
  };
}
