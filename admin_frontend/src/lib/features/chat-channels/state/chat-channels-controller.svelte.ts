import {
  clearChatMessages,
  deleteChatChannel,
  listChatChannels,
  type ChatChannelRow,
  type ChatHistoryMessage
} from '$lib/api/chat-channels';
import { listCharacters, type CharacterRow } from '$lib/api/characters';
import type { ChatChannelFormFields } from '$lib/features/chat-channels/shared/chat-channel-form';
import { createChatChannelsPreferences } from '$lib/preferences/chat-channels-preferences.svelte';
import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
import { createChatChannelsDialogs } from '$lib/features/chat-channels/state/chat-channels-dialogs.svelte';
import { createChatChannelsUiPrefs } from '$lib/features/chat-channels/state/chat-channels-ui-prefs.svelte';
import { createChatMessagesEngine } from '$lib/features/chat-channels/state/chat-messages-engine.svelte';
import { createChatCharacterResolved } from '$lib/features/chat-channels/state/chat-character-resolved.svelte';
import { createChatComposer } from '$lib/features/chat-channels/state/chat-composer.svelte';
import { createChatChannelForm } from '$lib/features/chat-channels/state/chat-channel-form.svelte';
import type { ChatChannelsTabPreference } from '$lib/preferences/keys';

/** Shared chat conversation engine — backs both the /chats Messages tab and the global overlay. */
export type ChatChannelsPageController = ReturnType<typeof createChatChannelsPageController>;

/** Chat channels Messages tab orchestration — URL prefs, REST, mic capture, modal wiring. Derived fields use getters per Svelte POJO-controller pattern. */
export function createChatChannelsPageController() {
  const toasts = createToastNotifier();
  const nav = createChatChannelsPreferences();
  let selectedChannelId = $state<string | null>(null);
  let channels = $state<ChatChannelRow[]>([]);
  let characters = $state<CharacterRow[]>([]);
  let channelsLoading = $state(true);
  let channelsError = $state<string | null>(null);
  /** Shared "channel admin mutation in progress" flag (form submit + delete + clear). */
  let busy = $state(false);
  /** Confirm/delete/discard overlay flags live here so destructive UX rules stay centralized. */
  const dlg = createChatChannelsDialogs({ isBusy: () => busy });
  /** Composer/bubble UI toggles (voice-reply, use-knowledge, disable-tools, stats, tools) — localStorage-backed. */
  const uiPrefs = createChatChannelsUiPrefs();
  /**
   * Live-conversation engine — message list + polling loop + agent typing/voice state.
   * Leased on/off screen by both surfaces; reads the controller-owned channel id back
   * via `getSelectedChannelId`. Backs BOTH the /chats Messages tab and the global overlay.
   */
  const engine = createChatMessagesEngine({ getSelectedChannelId: () => selectedChannelId });
  /** Create/edit channel form — lifecycle, dirty tracking, unsaved guard, photo + submit. */
  const form = createChatChannelForm({
    getCharacters: () => characters,
    getChannels: () => channels,
    isBusy: () => busy,
    setBusy: (b) => (busy = b),
    notify: toasts.notify,
    onSaved: () => refreshCurrent()
  });
  /** Idempotent boot guard so the shared engine starts (load channels/chars) exactly once. */
  let started = false;

  const selectedChannel = $derived(
    selectedChannelId
      ? (channels.find((channel) => String(channel.id) === selectedChannelId) ?? null)
      : null
  );

  /** Resolved TTS config for the selected channel's character — gates the "Get voice reply" toggle. */
  const charResolved = createChatCharacterResolved({
    getSelectedChannel: () => selectedChannel,
    uiPrefs
  });

  /** Message composer — draft box, mic capture, and the text/voice send flow. */
  const composer = createChatComposer({
    getSelectedChannelId: () => selectedChannelId,
    engine,
    uiPrefs,
    effectiveRequestVoiceReply: () => charResolved.effectiveRequestVoiceReply(),
    notify: toasts.notify
  });

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
    const messages = engine.messages;
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

  const notify = toasts.notify;

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
      engine.resetConversation();
    }
    selectedChannelId = nextChannelId;
    return selectedChannelId;
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
        engine.resetConversation();
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
      engine.clearConversation();
      charResolved.clear();
      return;
    }
    await engine.loadConversation(Number(channelId));
    void charResolved.refresh();
  }

  async function refreshCurrent() {
    engine.resetPollErrors();
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
      engine.resetConversation();
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
        engine.resetConversation();
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

  /**
   * One-time boot for the shared engine: message-engine runtime (visibility listener,
   * section-mounted flag) and the initial channel/character load. Safe to call from
   * both surfaces (page Messages tab and global overlay) — runs its body exactly once.
   * UI toggles are restored eagerly by `createChatChannelsUiPrefs()` at construction.
   */
  async function ensureStarted() {
    if (started) return;
    started = true;
    engine.startRuntime();
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
    if (selectedChannelId && engine.messages.length === 0 && !engine.messagesLoading) {
      await loadMessages();
    }
  }

  /** Overlay channel switch / manual reload — same as the page minus URL sync. */
  async function reloadMessages() {
    await loadMessages();
  }

  /** Overlay refresh button — reload channels + messages without touching the URL. */
  async function refreshConversation() {
    engine.resetPollErrors();
    await loadChannels();
    ensureSelectedChannel();
    await loadMessages();
  }

  function dispose() {
    engine.dispose();
  }

  return {
    mount,
    dispose,

    // Shared-singleton surface (global overlay + page lease coordination).
    ensureConversationLoaded,
    reloadMessages,
    refreshConversation,
    setPageMessagesActive: engine.setPageMessagesActive,
    setOverlayActive: engine.setOverlayActive,

    loadChannels,
    refreshCurrent,
    setActiveTab,
    syncNavFromUrl,

    openMessages,
    handleChannelSelect,

    characterLabel,
    openCreate: form.openCreate,
    openEdit: form.openEdit,

    channelFormBeforeClose: form.channelFormBeforeClose,
    finalizeChannelForm: form.finalizeChannelForm,
    cancelChannelFormExplicit: form.cancelChannelFormExplicit,

    submitForm: form.submitForm,

    closeDelete,

    openClearMessagesModal: dlg.openClearMessagesModal,
    closeClearMessagesModal,
    submitDelete,
    submitClearMessages,

    submitDraftText: composer.submitDraftText,
    beginRecording: composer.beginRecording,
    finalizeRecording: composer.finalizeRecording,
    discardRecording: composer.discardRecording,
    disposeActiveRecording: composer.disposeActiveRecording,

    get toast() {
      return toasts.toast;
    },
    get unsaved() {
      return form.unsaved;
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
        engine.resetConversation();
      }
      selectedChannelId = v;
    },
    get requestVoiceReplyUi() {
      return uiPrefs.requestVoiceReply;
    },
    set requestVoiceReplyUi(v: boolean) {
      uiPrefs.requestVoiceReply = v;
    },
    get useKnowledgeUi() {
      return uiPrefs.useKnowledge;
    },
    set useKnowledgeUi(v: boolean) {
      uiPrefs.useKnowledge = v;
    },
    get disableToolsUi() {
      return uiPrefs.disableTools;
    },
    set disableToolsUi(v: boolean) {
      uiPrefs.disableTools = v;
    },
    get showAgentTokensUi() {
      return uiPrefs.showAgentTokens;
    },
    set showAgentTokensUi(v: boolean) {
      uiPrefs.showAgentTokens = v;
    },
    get showAgentToolsUi() {
      return uiPrefs.showAgentTools;
    },
    set showAgentToolsUi(v: boolean) {
      uiPrefs.showAgentTools = v;
    },
    get draftMessage() {
      return composer.draftMessage;
    },
    set draftMessage(v: string) {
      composer.draftMessage = v;
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
      return engine.messages;
    },
    get messagesLoading(): boolean {
      return engine.messagesLoading;
    },
    get messagesError(): string | null {
      return engine.messagesError;
    },
    get messagesSyncing(): boolean {
      return engine.syncing;
    },
    get agentTyping(): boolean {
      return engine.agentTyping;
    },
    get agentVoiceGeneratingMessageId(): string | null {
      return engine.agentVoiceGeneratingMessageId;
    },
    get liveUpdatesPaused(): boolean {
      return engine.liveUpdatesPaused;
    },
    get busy(): boolean {
      return busy;
    },
    get formOpen(): boolean {
      return form.formOpen;
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
      return composer.recordingStartedAt;
    },
    get composingBusy(): boolean {
      return composer.composingBusy;
    },

    get modalChannelPhotoSrc(): string | null {
      return form.modalChannelPhotoSrc;
    },
    get formTitle(): string {
      return form.formTitle;
    },
    get formMode(): 'create' | 'edit' {
      return form.formMode;
    },
    get form(): ChatChannelFormFields {
      return form.form;
    },
    set form(v: ChatChannelFormFields) {
      form.form = v;
    },
    get pendingPhotoDataUrl(): string | null {
      return form.pendingPhotoDataUrl;
    },
    set pendingPhotoDataUrl(v: string | null) {
      form.pendingPhotoDataUrl = v;
    },
    get formError(): string | null {
      return form.formError;
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
      return charResolved.voiceReplyCheckboxDisabled;
    },
    get voiceReplyCheckboxHint(): string {
      return charResolved.voiceReplyCheckboxHint;
    },

    get channelFormDirty(): boolean {
      return form.channelFormDirty;
    }
  };
}
