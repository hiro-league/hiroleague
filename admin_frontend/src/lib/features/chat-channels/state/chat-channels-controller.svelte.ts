import { browser } from '$app/environment';
import { untrack } from 'svelte';
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
import { createChatChannelsPreferences } from '$lib/preferences/chat-channels-preferences.svelte';
import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
import { createChatChannelsDialogs } from '$lib/features/chat-channels/state/chat-channels-dialogs.svelte';
import {
  cursorFromMessages,
  mergeChatHistoryMessages,
  recentMessagePks,
  sortChatHistoryMessages,
  type ChatTailCursor
} from '$lib/features/chat-channels/state/chat-channel-message-merge';
import {
  BACKOFF_STEPS_MS,
  LIVE_UPDATES_PAUSED_AFTER_FAILURES,
  POLL_INTERVAL_MS,
  RECENT_RESYNC_K,
  TAIL_LIMIT
} from '$lib/features/chat-channels/state/chat-channels-poll-config';
import { PREF_KEYS, type ChatChannelsTabPreference } from '$lib/preferences/keys';
import {
  characterResolvedAllowsVoiceRequest,
  characterResolvedVoiceReplyControlHint
} from '$lib/features/characters/character-resolved-voice';

/** Shared chat conversation engine — backs both the /chats Messages tab and the global overlay. */
export type ChatChannelsPageController = ReturnType<typeof createChatChannelsPageController>;

/** Chat channels Messages tab orchestration — URL prefs, REST, mic capture, modal wiring. Derived fields use getters per Svelte POJO-controller pattern. */
export function createChatChannelsPageController() {
  const toasts = createToastNotifier();
  const nav = createChatChannelsPreferences();
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
  /** Per-message "use knowledge" toggle (default on); persisted like the voice-reply pref. */
  let useKnowledgeUi = $state(true);
  /** Per-message "disable tools" toggle (default off ⇒ tools on); overrides the chat.tools_enabled pref. */
  let disableToolsUi = $state(false);
  /** Token/cost stats on Messages bubbles; persisted like voice-reply pref. */
  let showAgentTokensUi = $state(true);
  /** Agent tool stack on Messages bubbles; persisted independently of stats. */
  let showAgentToolsUi = $state(true);
  let draftMessage = $state('');
  let recordingStartedAt = $state<number | null>(null);
  let composingBusy = $state(false);
  let tailCursor = $state<ChatTailCursor | null>(null);
  let syncing = $state(false);
  let pollErrorStreak = $state(0);
  let messagesSectionMounted = $state(false);
  let documentVisible = $state(true);
  let pollTimer: number | null = null;
  let pollTickInFlight = false;
  let optimisticMessagePk = -1;
  let agentTyping = $state(false);
  let agentVoicePendingSince = $state<string | null>(null);

  // Shared-singleton plumbing: this controller now backs BOTH the /chats Messages
  // tab and the global chat overlay. Polling is leased by whichever surface is
  // actually on screen (a persisted tab pref must NOT keep polling alive in the
  // background once you navigate away), so eligibility is OR-ed across surfaces.
  let pageMessagesActive = $state(false);
  let overlayActive = $state(false);
  /** Idempotent boot guard so the shared engine starts (load channels/chars) exactly once. */
  let started = false;

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

  const unsaved = createUnsavedGuard(
    () => channelFormDirty,
    () => formOpen,
    (next) => {
      if (!next) finalizeChannelForm();
    }
  );

  const selectedChannel = $derived(
    selectedChannelId
      ? (channels.find((channel) => String(channel.id) === selectedChannelId) ?? null)
      : null
  );

  /** Character browse photo only (no channel thumbnail fallback). */
  const messagesHeaderPhotoSrc = $derived.by(() => {
    const ch = selectedChannel;
    if (!ch) return null;
    const row = characters.find((c) => c.id === ch.character_id);
    return row?.photo_data_url ?? null;
  });

  const messagesHeaderChannelName = $derived.by(() => selectedChannel?.name ?? null);

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

  const messagesHeaderChannelHint = $derived.by(() => {
    const ch = selectedChannel;
    if (!ch) return '';
    const charPart = messagesHeaderCharacterName ? `${messagesHeaderCharacterName} · ` : '';
    return `${charPart}${ch.name} · id ${ch.id}`;
  });

  const liveUpdatesEligible = $derived(
    (pageMessagesActive || overlayActive) &&
      selectedChannelId !== null &&
      documentVisible &&
      messagesSectionMounted
  );

  const liveUpdatesPaused = $derived(
    pollErrorStreak >= LIVE_UPDATES_PAUSED_AFTER_FAILURES
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

  $effect(() => {
    if (!browser) return;
    if (liveUpdatesEligible) {
      untrack(startPolling);
      return () => untrack(stopPolling);
    }
    untrack(stopPolling);
  });

  const notify = toasts.notify;

  function currentPollIntervalMs() {
    const idx = Math.min(Math.max(pollErrorStreak - 1, 0), BACKOFF_STEPS_MS.length - 1);
    return pollErrorStreak <= 0 ? POLL_INTERVAL_MS : BACKOFF_STEPS_MS[idx];
  }

  function startPolling() {
    if (!browser || pollTimer !== null) return;
    void pollMessagesOnce();
    pollTimer = window.setInterval(() => {
      void pollMessagesOnce();
    }, currentPollIntervalMs());
  }

  function stopPolling() {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    syncing = false;
  }

  function restartPollingTimer() {
    if (!browser || !liveUpdatesEligible) return;
    stopPolling();
    pollTimer = window.setInterval(() => {
      void pollMessagesOnce();
    }, currentPollIntervalMs());
  }

  function resetPollErrors() {
    const hadBackoff = pollErrorStreak > 0;
    pollErrorStreak = 0;
    if (hadBackoff) restartPollingTimer();
  }

  function updateTailCursor() {
    tailCursor = cursorFromMessages(messages);
  }

  function updateAgentTypingFromIncoming(incoming: ChatHistoryMessage[]) {
    if (agentTyping && incoming.some((message) => message.sender_type !== 'user')) {
      agentTyping = false;
    }
  }

  function messageHasAudio(message: ChatHistoryMessage): boolean {
    return message.content.some((item) => item.content_type === 'audio');
  }

  function messageHasText(message: ChatHistoryMessage): boolean {
    return message.content.some((item) => item.content_type === 'text' && item.body.trim());
  }

  function updateAgentVoicePendingFromIncoming(incoming: ChatHistoryMessage[]) {
    const since = agentVoicePendingSince;
    if (!since) return;
    if (
      incoming.some(
        (message) =>
          message.sender_type !== 'user' &&
          message.created_at >= since &&
          messageHasAudio(message)
      )
    ) {
      agentVoicePendingSince = null;
    }
  }

  const agentVoiceGeneratingMessageId = $derived.by(() => {
    const since = agentVoicePendingSince;
    if (!since) return null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const message = messages[i];
      if (
        message &&
        message.sender_type !== 'user' &&
        message.created_at >= since &&
        messageHasText(message) &&
        !messageHasAudio(message)
      ) {
        return message.id;
      }
    }
    return null as string | null;
  });

  function handleVisibilityChange() {
    documentVisible = document.visibilityState === 'visible';
  }

  async function pollMessagesOnce() {
    if (pollTickInFlight || !liveUpdatesEligible || messagesLoading) return;
    const rawChannelId = selectedChannelId;
    const channelId = rawChannelId ? Number(rawChannelId) : NaN;
    if (!Number.isFinite(channelId)) return;

    if (tailCursor === null) {
      updateTailCursor();
      if (tailCursor === null) {
        if (!messages.some((message) => message.message_pk < 0)) return;
        pollTickInFlight = true;
        syncing = true;
        try {
          const payload = await listChatMessages(channelId);
          if (selectedChannelId !== rawChannelId || !liveUpdatesEligible) return;
          updateAgentTypingFromIncoming(payload.data);
          updateAgentVoicePendingFromIncoming(payload.data);
          messages = mergeChatHistoryMessages(messages, payload.data);
          updateTailCursor();
          resetPollErrors();
        } catch {
          pollErrorStreak += 1;
          restartPollingTimer();
        } finally {
          if (selectedChannelId === rawChannelId) {
            syncing = false;
          }
          pollTickInFlight = false;
        }
        return;
      }
    }

    pollTickInFlight = true;
    syncing = true;
    try {
      const cursor = tailCursor;
      const tailPayload = await listChatMessages(channelId, {
        after: cursor.created_at,
        afterId: cursor.external_id,
        limit: TAIL_LIMIT
      });
      if (selectedChannelId !== rawChannelId || !liveUpdatesEligible) return;
      if (tailPayload.data.length > 0) {
        updateAgentTypingFromIncoming(tailPayload.data);
        updateAgentVoicePendingFromIncoming(tailPayload.data);
        messages = mergeChatHistoryMessages(messages, tailPayload.data);
        updateTailCursor();
      }

      if (!liveUpdatesEligible) return;
      const messagePks = recentMessagePks(messages, RECENT_RESYNC_K);
      if (messagePks.length > 0) {
        const resyncPayload = await listChatMessages(channelId, { messagePks });
        if (selectedChannelId !== rawChannelId || !liveUpdatesEligible) return;
        if (resyncPayload.data.length > 0) {
          updateAgentVoicePendingFromIncoming(resyncPayload.data);
          messages = mergeChatHistoryMessages(messages, resyncPayload.data);
          updateTailCursor();
        }
      }
      resetPollErrors();
    } catch {
      pollErrorStreak += 1;
      restartPollingTimer();
    } finally {
      if (selectedChannelId === rawChannelId) {
        syncing = false;
      }
      pollTickInFlight = false;
    }
  }

  function addOptimisticMessage(message: ChatHistoryMessage) {
    if (
      message.message_pk < 0 &&
      messages.some((existing) => existing.id === message.id && existing.message_pk > 0)
    ) {
      return;
    }
    messages = mergeChatHistoryMessages(messages, [message]);
  }

  /** Restore tab/channel from `createChatChannelsPreferences().initialize()`. */
  function initializeNavigation() {
    nav.initialize();
    // Only override the channel when the URL pins one. Otherwise keep whatever the
    // shared engine already has (e.g. the overlay picked a channel before /chats was
    // ever visited) and let `ensureSelectedChannel()` fall back to the first channel.
    const fromUrl = nav.readChannelIdFromLocation();
    if (fromUrl) selectedChannelId = fromUrl;
  }

  async function syncUrl() {
    await nav.syncNav(selectedChannelId);
  }

  /**
   * Re-apply `?tab=`/`?channel_id=` after a *same-route* navigation. `mount()`'s
   * `initializeNavigation()` runs only once, so without this the global overlay's
   * "open full page" link (which pushes `?tab=messages` while already on /chats)
   * would update the URL but leave the strip stuck on Channels. Flipping the tab
   * here lets the live-updates lease effect load messages on its own.
   */
  function syncNavFromUrl() {
    nav.syncActiveTabFromUrl();
    const fromUrl = nav.readChannelIdFromLocation();
    if (fromUrl && fromUrl !== selectedChannelId) selectedChannelId = fromUrl;
  }

  function ensureSelectedChannel(): string | null {
    if (selectedChannelId && channels.some((channel) => String(channel.id) === selectedChannelId)) {
      return selectedChannelId;
    }
    const nextChannelId = channels.length > 0 ? String(channels[0].id) : null;
    if (selectedChannelId !== nextChannelId) {
      messages = [];
      tailCursor = null;
      agentTyping = false;
      agentVoicePendingSince = null;
    }
    selectedChannelId = nextChannelId;
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
        messages = [];
        tailCursor = null;
        agentTyping = false;
        agentVoicePendingSince = null;
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
      tailCursor = null;
      agentTyping = false;
      agentVoicePendingSince = null;
      messagesError = null;
      clearCharacterResolvedForMessages();
      return;
    }

    messagesLoading = true;
    messagesError = null;
    messages = [];
    tailCursor = null;
    try {
      const payload = await listChatMessages(Number(channelId));
      if (payload.data.at(-1)?.sender_type !== 'user') {
        agentTyping = false;
      }
      updateAgentVoicePendingFromIncoming(payload.data);
      messages = sortChatHistoryMessages(payload.data);
      updateTailCursor();
      resetPollErrors();
    } catch (err) {
      messagesError = err instanceof Error ? err.message : 'Failed to load messages.';
    } finally {
      messagesLoading = false;
      void refreshCharacterResolvedForMessagesChannel();
    }
  }

  async function refreshCurrent() {
    resetPollErrors();
    await loadChannels();
    if (nav.activeTab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
    }
  }

  async function setActiveTab(tab: ChatChannelsTabPreference) {
    if (tab === 'messages') {
      ensureSelectedChannel();
      await nav.setActiveTab(tab, selectedChannelId);
      await loadMessages();
      return;
    }
    await nav.setActiveTab(tab);
  }

  async function openMessages(row: ChatChannelRow) {
    const id = String(row.id);
    if (selectedChannelId !== id) {
      messages = [];
      tailCursor = null;
      agentTyping = false;
      agentVoicePendingSince = null;
    }
    selectedChannelId = id;
    await nav.setActiveTab('messages', id);
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

  /** Stack shared unsaved guard above editor when closing with a dirty form. */
  function channelFormBeforeClose(_source: 'backdrop' | 'escape' | 'header'): boolean {
    void _source;
    if (!channelFormDirty) return true;
    if (unsaved.unsavedModalOpen) return false;
    void requestChannelFormDiscardConfirm();
    return false;
  }

  async function requestChannelFormDiscardConfirm() {
    if (await unsaved.confirmDiscard()) {
      finalizeChannelForm();
    }
  }

  function finalizeChannelForm() {
    formOpen = false;
    formBaseline = null;
    pendingPhotoDataUrl = null;
  }

  async function cancelChannelFormExplicit() {
    if (busy) return;
    if (channelFormDirty && !(await unsaved.confirmDiscard())) return;
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
        tailCursor = null;
        agentTyping = false;
        agentVoicePendingSince = null;
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
      const requestVoiceReply = effectiveRequestVoiceReplyForSend();
      const sent = await sendChatMessage(id, {
        text,
        request_voice_reply: requestVoiceReply || undefined,
        use_knowledge: useKnowledgeUi,
        disable_tools: disableToolsUi || undefined
      });
      const sentAt = new Date().toISOString();
      draftMessage = '';
      addOptimisticMessage({
        id: sent.data.message_id,
        message_pk: optimisticMessagePk--,
        channel_id: id,
        sender_type: 'user',
        sender_id: 'admin',
        created_at: sentAt,
        content: [{ content_type: 'text', body: text }]
      });
      agentTyping = true;
      agentVoicePendingSince = requestVoiceReply ? sentAt : null;
      notify('success', 'Message sent.');
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
      const requestVoiceReply = effectiveRequestVoiceReplyForSend();
      const sent = await sendChatMessage(id, {
        audio_base64: b64,
        audio_mime_type: effectiveMime,
        audio_duration_ms: duration_ms,
        request_voice_reply: requestVoiceReply || undefined,
        use_knowledge: useKnowledgeUi,
        disable_tools: disableToolsUi || undefined
      });
      const sentAt = new Date().toISOString();
      addOptimisticMessage({
        id: sent.data.message_id,
        message_pk: optimisticMessagePk--,
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
      agentTyping = true;
      agentVoicePendingSince = requestVoiceReply ? sentAt : null;
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

  /**
   * One-time boot for the shared engine: visibility listener, persisted UI prefs,
   * and the initial channel/character load. Safe to call from both surfaces (page
   * Messages tab and global overlay) — runs its body exactly once.
   */
  async function ensureStarted() {
    if (started) return;
    started = true;
    messagesSectionMounted = true;
    if (browser) {
      documentVisible = document.visibilityState === 'visible';
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }
    try {
      const raw = localStorage.getItem(PREF_KEYS.chatChannelsVoiceReply);
      if (raw === '1') requestVoiceReplyUi = true;
      if (raw === '0') requestVoiceReplyUi = false;
      const rawKnowledge = localStorage.getItem(PREF_KEYS.chatChannelsUseKnowledge);
      if (rawKnowledge === '1') useKnowledgeUi = true;
      if (rawKnowledge === '0') useKnowledgeUi = false;
      const rawDisableTools = localStorage.getItem(PREF_KEYS.chatChannelsDisableTools);
      if (rawDisableTools === '1') disableToolsUi = true;
      if (rawDisableTools === '0') disableToolsUi = false;
      const rawTokens = localStorage.getItem(PREF_KEYS.chatChannelsShowAgentTelemetry);
      if (rawTokens === '0') showAgentTokensUi = false;
      if (rawTokens === '1') showAgentTokensUi = true;
      const rawTools = localStorage.getItem(PREF_KEYS.chatChannelsShowAgentTools);
      if (rawTools === '0') showAgentToolsUi = false;
      if (rawTools === '1') showAgentToolsUi = true;
    } catch {
      /* ignore quota / private mode */
    }
    await loadCharacters();
    await loadChannels();
  }

  /** /chats Messages tab entry — URL-driven channel restore. */
  async function mount() {
    await ensureStarted();
    initializeNavigation();
    if (nav.activeTab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
    }
  }

  /**
   * Global overlay entry — no URL writes (it floats over arbitrary pages). Ensures
   * a channel is selected and its messages are loaded once when the overlay opens.
   */
  async function ensureConversationLoaded() {
    await ensureStarted();
    ensureSelectedChannel();
    if (selectedChannelId && messages.length === 0 && !messagesLoading) {
      await loadMessages();
    }
  }

  /** Overlay channel switch / manual reload — same as the page minus URL sync. */
  async function reloadMessages() {
    await loadMessages();
  }

  /** Overlay refresh button — reload channels + messages without touching the URL. */
  async function refreshConversation() {
    resetPollErrors();
    await loadChannels();
    ensureSelectedChannel();
    await loadMessages();
  }

  function setPageMessagesActive(active: boolean) {
    pageMessagesActive = active;
  }

  function setOverlayActive(active: boolean) {
    overlayActive = active;
  }

  function dispose() {
    messagesSectionMounted = false;
    if (browser) {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    }
    stopPolling();
  }

  return {
    mount,
    dispose,

    // Shared-singleton surface (global overlay + page lease coordination).
    ensureConversationLoaded,
    reloadMessages,
    refreshConversation,
    setPageMessagesActive,
    setOverlayActive,

    loadChannels,
    refreshCurrent,
    setActiveTab,
    syncNavFromUrl,

    openMessages,
    handleChannelSelect,

    characterLabel,
    openCreate,
    openEdit,

    channelFormBeforeClose,
    finalizeChannelForm,
    cancelChannelFormExplicit,

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
      return toasts.toast;
    },
    get unsaved() {
      return unsaved;
    },
    get activeTab() {
      return nav.activeTab;
    },

    /** Messages panel two-way binds read/write `$state` in this controller via getters/setters. */
    get selectedChannelId() {
      return selectedChannelId;
    },
    set selectedChannelId(v: string | null) {
      if (selectedChannelId !== v) {
        messages = [];
        tailCursor = null;
        agentTyping = false;
        agentVoicePendingSince = null;
      }
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
    get useKnowledgeUi() {
      return useKnowledgeUi;
    },
    set useKnowledgeUi(v: boolean) {
      useKnowledgeUi = v;
      try {
        localStorage.setItem(PREF_KEYS.chatChannelsUseKnowledge, v ? '1' : '0');
      } catch {
        /* ignore */
      }
    },
    get disableToolsUi() {
      return disableToolsUi;
    },
    set disableToolsUi(v: boolean) {
      disableToolsUi = v;
      try {
        localStorage.setItem(PREF_KEYS.chatChannelsDisableTools, v ? '1' : '0');
      } catch {
        /* ignore */
      }
    },
    get showAgentTokensUi() {
      return showAgentTokensUi;
    },
    set showAgentTokensUi(v: boolean) {
      showAgentTokensUi = v;
      try {
        localStorage.setItem(PREF_KEYS.chatChannelsShowAgentTelemetry, v ? '1' : '0');
      } catch {
        /* ignore */
      }
    },
    get showAgentToolsUi() {
      return showAgentToolsUi;
    },
    set showAgentToolsUi(v: boolean) {
      showAgentToolsUi = v;
      try {
        localStorage.setItem(PREF_KEYS.chatChannelsShowAgentTools, v ? '1' : '0');
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
    get messagesSyncing(): boolean {
      return syncing;
    },
    get agentTyping(): boolean {
      return agentTyping;
    },
    get agentVoiceGeneratingMessageId(): string | null {
      return agentVoiceGeneratingMessageId;
    },
    get liveUpdatesPaused(): boolean {
      return liveUpdatesPaused;
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
    get messagesHeaderChannelName(): string | null {
      return messagesHeaderChannelName;
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
