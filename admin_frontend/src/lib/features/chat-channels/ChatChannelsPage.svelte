<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import {
    Edit,
    FileX2,
    ImageIcon,
    MessageSquare,
    Mic,
    Plus,
    RefreshCw,
    Send,
    Square,
    Trash2,
    Upload
  } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import {
    clearChatMessages,
    createChatChannel,
    deleteChatChannel,
    historyMessageFirstAudio,
    historyMessageText,
    listChatChannels,
    listChatMessages,
    sendChatMessage,
    updateChatChannel,
    uploadChatChannelPhoto,
    type ChatChannelPayload,
    type ChatChannelRow,
    type ChatHistoryMessage
  } from '$lib/api/chat-channels';
  import ChatMessageAttachmentAudio from '$lib/features/chat-channels/ChatMessageAttachmentAudio.svelte';
  import {
    cycleChatAudioSpeed,
    formatChatAudioSpeedLabel,
    chatAudioPlaybackRate
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import { listCharacters, type CharacterRow } from '$lib/api/characters';
  import FormField from '$lib/components/ui/form-field.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { PREF_KEYS, type ChatChannelsTabPreference } from '$lib/preferences/keys';
  import { readSessionString, writeSessionString } from '$lib/preferences/storage';
  import Modal from '$lib/ui/Modal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { cn } from '$lib/utils';

  type NotifyKind = 'success' | 'error' | 'info' | 'warning';

  type ChannelForm = {
    name: string;
    characterId: string;
    description: string;
  };

  type FormBaseline = {
    name: string;
    characterId: string;
    description: string;
    pendingPhotoDataUrl: string | null;
  };

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
  let formOpen = $state(false);
  let formMode = $state<'create' | 'edit'>('create');
  let editingChannelId = $state<number | null>(null);
  let formError = $state<string | null>(null);
  let form = $state<ChannelForm>({ name: '', characterId: '', description: '' });
  /** New image chosen in the modal; uploaded after save completes. */
  let pendingPhotoDataUrl = $state<string | null>(null);
  let discardConfirmOpen = $state(false);
  let channelPhotoInput = $state<HTMLInputElement | null>(null);
  /** Snapshot when opening the dialog — detects unsaved changes for dismiss guarding. */
  let formBaseline = $state<FormBaseline | null>(null);
  let deleteTarget = $state<ChatChannelRow | null>(null);
  let clearMessagesConfirmOpen = $state(false);
  /** Voice reply routing flag for outgoing admin tool calls (parity with Flutter). */
  let requestVoiceReplyUi = $state(false);
  let draftMessage = $state('');
  /** Browser mic recorder — outbound audio uses same UnifiedMessage wire shape as Flutter. */
  let mediaRecorderObj: MediaRecorder | null = null;
  let recordingChunks: Blob[] = [];
  let recordingStartedAt = $state<number | null>(null);
  let composingBusy = $state(false);

  const selectedChannel = $derived(
    selectedChannelId
      ? (channels.find((channel) => String(channel.id) === selectedChannelId) ?? null)
      : null
  );

  /** Character → channel thumbnail → placeholder: header avatar for Messages tab. */
  const messagesHeaderPhotoSrc = $derived.by(() => {
    if (!selectedChannel) return null;
    const row = characters.find((c) => c.id === selectedChannel.character_id);
    return row?.photo_data_url ?? selectedChannel.photo_data_url ?? null;
  });

  const messagesHeaderCharacterName = $derived.by(() => {
    if (!selectedChannel) return null;
    const row = characters.find((c) => c.id === selectedChannel.character_id);
    return row?.name ?? selectedChannel.character?.name ?? selectedChannel.character_id;
  });

  /** Latest user message sender_id for header device line (replaces per-bubble sender). */
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

  /** Channel label for tooltips — third header line moved here so layout stays two text lines. */
  const messagesHeaderChannelHint = $derived.by(() =>
    selectedChannel ? `${selectedChannel.name} · id ${selectedChannel.id}` : ''
  );

  const formTitle = $derived(
    formMode === 'create' ? 'New conversation channel' : 'Edit conversation channel'
  );

  /** Channel thumbnail: pending upload overrides server preview while editing. */
  const modalChannelPhotoSrc = $derived(
    pendingPhotoDataUrl ??
      (formMode === 'edit' && editingChannelId !== null
        ? (channels.find((c) => c.id === editingChannelId)?.photo_data_url ?? null)
        : null)
  );

  const channelFormDirty = $derived.by(() => {
    if (!formOpen || !formBaseline) return false;
    return (
      form.name !== formBaseline.name ||
      form.characterId !== formBaseline.characterId ||
      form.description !== formBaseline.description ||
      (pendingPhotoDataUrl ?? null) !== (formBaseline.pendingPhotoDataUrl ?? null)
    );
  });

  function snapshotBaseline(): FormBaseline {
    return {
      name: form.name,
      characterId: form.characterId,
      description: form.description,
      pendingPhotoDataUrl: pendingPhotoDataUrl ?? null
    };
  }

  function channelFormBeforeClose(_source: 'backdrop' | 'escape' | 'header') {
    void _source;
    // Discard dialog is stacked above the editor; defer dismiss to that Modal first.
    if (discardConfirmOpen) return false;
    if (!channelFormDirty) return true;
    discardConfirmOpen = true;
    return false;
  }

  function finalizeChannelForm() {
    formOpen = false;
    discardConfirmOpen = false;
    formBaseline = null;
    pendingPhotoDataUrl = null;
  }

  function cancelChannelFormExplicit() {
    if (busy) return;
    finalizeChannelForm();
  }

  function keepEditingAfterDismissAttempt() {
    discardConfirmOpen = false;
  }

  function discardUnsavedChannelFormAndClose() {
    discardConfirmOpen = false;
    finalizeChannelForm();
  }

  function normalizeTab(raw: string | null): ChatChannelsTabPreference | null {
    return raw === 'channels' || raw === 'messages' ? raw : null;
  }

  function notify(kind: NotifyKind, message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  function initializeNavigation() {
    activeTab =
      normalizeTab(page.url.searchParams.get('tab')) ??
      normalizeTab(readSessionString(PREF_KEYS.chatChannelsActiveTab)) ??
      'channels';
    selectedChannelId = page.url.searchParams.get('channel_id');
  }

  async function syncUrl() {
    writeSessionString(PREF_KEYS.chatChannelsActiveTab, activeTab);

    const nextUrl = new URL(page.url);
    nextUrl.searchParams.set('tab', activeTab);
    if (activeTab === 'messages' && selectedChannelId) {
      nextUrl.searchParams.set('channel_id', selectedChannelId);
    } else {
      nextUrl.searchParams.delete('channel_id');
    }
    await goto(`${nextUrl.pathname}${nextUrl.search}`, {
      keepFocus: true,
      noScroll: true,
      replaceState: true
    });
  }

  function ensureSelectedChannel() {
    if (selectedChannelId && channels.some((channel) => String(channel.id) === selectedChannelId)) {
      return selectedChannelId;
    }
    selectedChannelId = channels.length > 0 ? String(channels[0].id) : null;
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
    formBaseline = snapshotBaseline();
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
    formBaseline = snapshotBaseline();
    formOpen = true;
  }

  function onPhotoFile(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = () => {
      pendingPhotoDataUrl = typeof reader.result === 'string' ? reader.result : null;
      input.value = '';
    };
    reader.readAsDataURL(file);
  }

  function parseForm(): ChatChannelPayload | null {
    const name = form.name.trim();
    const characterId = form.characterId.trim();

    if (!name || !characterId) {
      formError = 'Name and character are required.';
      return null;
    }

    formError = null;
    return {
      name,
      character_id: characterId,
      description: form.description.trim()
    };
  }

  async function submitForm() {
    const payload = parseForm();
    if (!payload) return;

    busy = true;
    formError = null;
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
    if (busy) return;
    deleteTarget = null;
  }

  async function submitDelete() {
    if (!deleteTarget) return;

    busy = true;
    try {
      const deletedId = deleteTarget.id;
      await deleteChatChannel(deletedId);
      notify('success', 'Channel deleted.');
      deleteTarget = null;
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

  async function submitClearMessages() {
    const id = selectedChannelId ? Number(selectedChannelId) : NaN;
    if (!Number.isFinite(id)) return;

    busy = true;
    try {
      await clearChatMessages(id);
      clearMessagesConfirmOpen = false;
      notify('success', 'All messages were cleared.');
      await loadChannels();
      await loadMessages();
    } catch (err) {
      notify(
        'error',
        err instanceof Error ? err.message : 'Failed to clear messages.'
      );
    } finally {
      busy = false;
    }
  }

  function pickRecordingMime(): string | undefined {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
    if (typeof MediaRecorder === 'undefined') return undefined;
    for (const c of candidates) {
      if (MediaRecorder.isTypeSupported(c)) return c;
    }
    return undefined;
  }

  function uint8ToBase64(u8: Uint8Array): string {
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < u8.length; i += chunkSize) {
      binary += String.fromCharCode(...u8.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  }

  async function submitDraftText() {
    const id = selectedChannelId ? Number(selectedChannelId) : NaN;
    const text = draftMessage.trim();
    if (!Number.isFinite(id) || !text) return;
    composingBusy = true;
    try {
      await sendChatMessage(id, {
        text,
        request_voice_reply: requestVoiceReplyUi || undefined,
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

  /** Start microphone capture — same WebM/Opus + base64 pipeline as Hiro mobile. */
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
      const mime = pickRecordingMime();
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

  /** Stop recorder, assemble blob, POST ``message_send`` with ``audio_*`` params. */
  async function finalizeRecording() {
    if (!mediaRecorderObj || recordingStartedAt === null) return;
    const mr = mediaRecorderObj;
    const started = recordingStartedAt;
    const id = Number(selectedChannelId);

    recordingStartedAt = null;
    mediaRecorderObj = null;

    await new Promise<void>((resolve) => {
      mr.addEventListener('stop', () => resolve(), { once: true });
      try {
        mr.stop();
      } catch {
        resolve();
      }
    });
    mr.stream.getTracks().forEach((t) => t.stop());

    composingBusy = true;
    try {
      const mimeType =
        mr.mimeType || (recordingChunks[0]?.type ?? 'audio/webm');
      const blob = new Blob(recordingChunks, { type: mimeType });
      recordingChunks = [];
      const duration_ms = Math.max(1, Math.round(performance.now() - started));
      const buf = await blob.arrayBuffer();
      const b64 = uint8ToBase64(new Uint8Array(buf));
      await sendChatMessage(id, {
        audio_base64: b64,
        audio_mime_type: mimeType,
        audio_duration_ms: duration_ms,
        request_voice_reply: requestVoiceReplyUi || undefined,
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
    mr.stream.getTracks().forEach((t) => t.stop());
    await new Promise<void>((resolve) => {
      mr.addEventListener('stop', () => resolve(), { once: true });
      try {
        mr.stop();
      } catch {
        resolve();
      }
    });
  }

  onMount(async () => {
    initializeNavigation();
    await loadCharacters();
    await loadChannels();
    if (activeTab === 'messages') {
      ensureSelectedChannel();
      await syncUrl();
      await loadMessages();
    }
  });
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Communication</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Chat channels</h2>
    </div>
    <div class="inline-flex rounded-lg border bg-card p-1" role="tablist" aria-label="Chat channel sections">
      <Button
        class={cn(
          'shadow-none',
          activeTab === 'channels' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={activeTab === 'channels' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => setActiveTab('channels')}
      >
        Channels
      </Button>
      <Button
        class={cn(
          'shadow-none',
          activeTab === 'messages' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={activeTab === 'messages' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => setActiveTab('messages')}
      >
        Messages
      </Button>
    </div>
  </div>

  {#if activeTab === 'channels'}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Channels</h3>
          <span class="font-sans text-sm text-muted-foreground">{channels.length} conversation threads</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" onclick={loadChannels}><RefreshCw size={15} /> Refresh</Button>
          <Button onclick={openCreate}><Plus size={15} /> Add channel</Button>
        </div>
      </div>

      {#if channelsLoading}
        <p class="text-muted-foreground">Loading chat channels...</p>
      {:else if channelsError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load chat channels</strong>
          <span class="block text-sm">{channelsError}</span>
        </div>
      {:else if channels.length === 0}
        <p class="text-muted-foreground">No conversation channels yet.</p>
      {:else}
        <div class="overflow-x-auto rounded-md border">
          <div class="min-w-[1120px]">
            <div
              class="grid grid-cols-[72px_minmax(0,1fr)_90px_minmax(0,1.1fr)_minmax(0,1fr)_160px_150px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground"
            >
              <span>ID</span>
              <span>Name</span>
              <span>Type</span>
              <span>Description</span>
              <span>Character</span>
              <span>Last activity</span>
              <span>Actions</span>
            </div>
            {#each channels as row (row.id)}
              <div
                class="grid min-h-16 grid-cols-[72px_minmax(0,1fr)_90px_minmax(0,1.1fr)_minmax(0,1fr)_160px_150px] gap-3 border-t px-3 py-3"
              >
                <span class="font-mono text-xs text-muted-foreground">{row.id}</span>
                <span class="flex min-w-0 items-center gap-2">
                  {#if row.photo_data_url}
                    <img
                      src={row.photo_data_url}
                      alt=""
                      class="size-9 shrink-0 rounded-md border object-cover"
                    />
                  {/if}
                  <span class="truncate font-sans text-sm font-semibold" title={row.name}>{row.name}</span>
                </span>
                <span><Badge variant="secondary">direct</Badge></span>
                <span class="truncate text-xs text-muted-foreground" title={row.description ?? ''}>
                  {row.description ?? '—'}
                </span>
                <span class="truncate font-mono text-xs text-muted-foreground" title={row.character_id}>
                  {row.character?.name ?? row.character_id}
                </span>
                <span class="truncate text-xs text-muted-foreground">{formatChatTimestamp(row.last_message_at)}</span>
                <span class="flex justify-end gap-1">
                  <Button size="icon" variant="ghost" onclick={() => openMessages(row)} title="Messages">
                    <MessageSquare size={15} />
                  </Button>
                  <Button size="icon" variant="ghost" onclick={() => openEdit(row)} title="Edit">
                    <Edit size={15} />
                  </Button>
                  {#if !row.is_lowest_id_channel}
                    <Button size="icon" variant="ghost" onclick={() => (deleteTarget = row)} title="Delete">
                      <Trash2 size={15} />
                    </Button>
                  {/if}
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {:else}
    <section
      class="flex h-[min(calc(100vh-10rem),56rem)] min-h-[16rem] flex-col gap-4 overflow-hidden rounded-lg border bg-card p-5 shadow-sm"
    >
      <div class="flex shrink-0 min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex min-w-0 items-center gap-3">
          {#if messagesHeaderPhotoSrc}
            <img
              src={messagesHeaderPhotoSrc}
              alt=""
              class="size-14 shrink-0 rounded-xl border bg-muted object-cover"
              title={messagesHeaderChannelHint}
            />
          {:else}
            <div
              class="flex size-14 shrink-0 items-center justify-center rounded-xl border border-dashed bg-muted text-muted-foreground"
              aria-hidden="true"
              title={messagesHeaderChannelHint}
            >
              <ImageIcon size={24} />
            </div>
          {/if}
          <div class="min-w-0">
            <h3 class="text-lg font-semibold leading-tight">Messages</h3>
            {#if selectedChannel}
              <p class="mt-0.5 truncate font-sans text-sm leading-tight" title={messagesHeaderChannelHint}>
                <span class="font-semibold text-foreground">{messagesHeaderCharacterName}</span>
                {#if messagesHeaderDeviceId}
                  <span class="text-muted-foreground"> · </span>
                  <span class="font-mono text-[11px] text-muted-foreground">{messagesHeaderDeviceId}</span>
                {/if}
              </p>
            {:else}
              <span class="mt-0.5 block font-sans text-sm text-muted-foreground">No channel selected</span>
            {/if}
          </div>
        </div>
        <div class="flex shrink-0 flex-wrap items-center gap-2">
          {#if channels.length > 0}
            <select
              class="h-9 min-w-56 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              bind:value={selectedChannelId}
              onchange={handleChannelSelect}
              aria-label="Message channel"
              title={messagesHeaderChannelHint}
            >
              {#each channels as channel (channel.id)}
                <option value={String(channel.id)}>{channel.name} (id {channel.id})</option>
              {/each}
            </select>
          {/if}
          <Button
            variant="outline"
            class="border-destructive/60 text-destructive hover:bg-destructive/10"
            disabled={busy || !selectedChannelId || channelsLoading}
            onclick={() => (clearMessagesConfirmOpen = true)}
            title="Remove all messages in this channel"
          >
            <FileX2 size={15} /> Clear messages
          </Button>
          <Button variant="outline" onclick={cycleChatAudioSpeed} title="Cycle playback speed (applies to all clips)">
            {formatChatAudioSpeedLabel($chatAudioPlaybackRate)}
          </Button>
          <Button variant="outline" onclick={refreshCurrent}><RefreshCw size={15} /> Refresh</Button>
        </div>
      </div>

      <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
        {#if channelsLoading}
        <p class="shrink-0 text-muted-foreground">Loading chat channels...</p>
      {:else if channelsError}
        <div class="shrink-0 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load chat channels</strong>
          <span class="block text-sm">{channelsError}</span>
        </div>
      {:else if channels.length === 0}
        <p class="shrink-0 text-muted-foreground">No conversation channels. Create one on the Channels tab.</p>
      {:else if messagesLoading}
        <p class="shrink-0 text-muted-foreground">Loading messages...</p>
      {:else if messagesError}
        <div class="shrink-0 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load messages</strong>
          <span class="block text-sm">{messagesError}</span>
        </div>
      {:else}
        <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden">
          {#if messages.length === 0}
            <p class="shrink-0 text-muted-foreground">No messages in this channel yet.</p>
          {:else}
            <div class="min-h-0 min-w-0 flex-1 overflow-y-auto rounded-md border bg-background/45 p-4">
              <div class="grid max-w-3xl gap-3">
                {#each messages as message (message.id)}
                  {@const isUser = message.sender_type === 'user'}
                  {@const textBody = historyMessageText(message)}
                  {@const audioItem = historyMessageFirstAudio(message)}
                  <div class={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
                    <div
                      class={cn(
                        'grid max-w-[85%] gap-1.5 rounded-2xl px-4 py-2.5 shadow-sm',
                        isUser
                          ? 'bg-primary text-primary-foreground'
                          : 'border border-border bg-secondary text-secondary-foreground dark:border-border dark:bg-secondary/40 dark:text-foreground dark:ring-1 dark:ring-border/80'
                      )}
                    >
                      {#if textBody}
                        <p class="whitespace-pre-wrap break-words font-sans text-sm">{textBody}</p>
                      {:else if !audioItem}
                        <p class="whitespace-pre-wrap break-words font-sans text-sm opacity-80">No text body</p>
                      {/if}
                      {#if audioItem && selectedChannelId}
                        <ChatMessageAttachmentAudio
                          channelId={Number(selectedChannelId)}
                          externalMessageId={message.id}
                          audioItem={audioItem}
                        />
                      {/if}
                      {#if message.created_at}
                        <div class="flex justify-end pt-0.5">
                          <span
                            class={cn(
                              'tabular-nums font-sans text-[10px] leading-none opacity-40',
                              isUser && 'opacity-50'
                            )}
                          >
                            {formatChatTimestamp(message.created_at)}
                          </span>
                        </div>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
          {#if selectedChannelId && channels.length > 0 && !channelsError}
            <div class="shrink-0 space-y-2 border-border border-t pt-3 font-sans text-sm">
              <label class="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                <input type="checkbox" bind:checked={requestVoiceReplyUi} class="accent-primary h-4 w-4 shrink-0" />
                Ask for voice reply (same as mobile routing flag)
              </label>
              {#if recordingStartedAt !== null}
                <div class="flex flex-wrap items-center gap-3">
                  <span class="font-medium text-destructive tabular-nums">Recording…</span>
                  <Button size="sm" onclick={() => finalizeRecording()} disabled={composingBusy}>
                    <Square size={14} /> Stop & send
                  </Button>
                  <Button size="sm" variant="outline" onclick={() => discardRecording()} disabled={composingBusy}>
                    Cancel
                  </Button>
                </div>
              {:else}
                <div class="flex flex-wrap items-end gap-2">
                  <textarea
                    class="focus-visible:ring-ring min-h-[2.75rem] flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 md:min-w-[16rem]"
                    placeholder="Send as workspace owner…"
                    rows="2"
                    bind:value={draftMessage}
                    onkeydown={(ev) => {
                      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') void submitDraftText();
                    }}
                    disabled={composingBusy}
                  ></textarea>
                  <Button
                    title="Send (Ctrl/Cmd + Enter)"
                    disabled={composingBusy || !draftMessage.trim()}
                    onclick={submitDraftText}
                  >
                    <Send size={15} />
                  </Button>
                  <Button
                    variant="secondary"
                    title="Hold to capture (click to start)"
                    disabled={composingBusy}
                    onclick={() => beginRecording()}
                  >
                    <Mic size={15} /> Mic
                  </Button>
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/if}
      </div>
    </section>
  {/if}
</section>

<ToastHost {toast} />

<Modal
  open={clearMessagesConfirmOpen}
  title="Clear all messages in this channel?"
  onClose={() => {
    if (!busy) clearMessagesConfirmOpen = false;
  }}
>
  <p class="font-sans text-sm text-muted-foreground">
    This removes every message and attachment in
    <strong class="text-foreground">{selectedChannel?.name ?? 'this channel'}</strong>
    on the server. The channel itself stays. Hiro devices pick this up on the next
    <span class="font-mono text-xs">channels.list</span> sync.
  </p>
  {#snippet footer()}
    <Button variant="outline" disabled={busy} onclick={() => (clearMessagesConfirmOpen = false)}>
      Cancel
    </Button>
    <Button variant="destructive" disabled={busy} onclick={submitClearMessages}>Clear messages</Button>
  {/snippet}
</Modal>

<Modal
  open={formOpen}
  title={formTitle}
  onBeforeClose={channelFormBeforeClose}
  onClose={finalizeChannelForm}
>
  <div class="grid gap-6 lg:grid-cols-[160px_minmax(0,1fr)] lg:items-start [&_.admin-ui-form-field]:mb-0">
    <div class="grid justify-items-start gap-3">
      <input
        class="hidden"
        type="file"
        accept="image/*"
        bind:this={channelPhotoInput}
        onchange={onPhotoFile}
      />
      <button
        type="button"
        class="overflow-hidden rounded-md border bg-muted/30 p-0 text-left ring-offset-background transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onclick={() => channelPhotoInput?.click()}
      >
        {#if modalChannelPhotoSrc}
          <img class="size-36 object-cover sm:size-40" src={modalChannelPhotoSrc} alt="" />
        {:else}
          <span class="grid size-36 place-items-center text-muted-foreground sm:size-40">
            <ImageIcon size={40} />
          </span>
        {/if}
      </button>
      <Button variant="outline" class="w-full max-w-40" onclick={() => channelPhotoInput?.click()}>
        <Upload size={15} /> Photo
      </Button>
    </div>

    <div class="grid min-w-0 gap-4">
      <FormField label="Display name" class="mb-4 w-full md:max-w-[33%] md:min-w-[12rem]">
        {#snippet children()}
          <input bind:value={form.name} autocomplete="off" />
        {/snippet}
      </FormField>

      <FormField label="Description" class="mb-4">
        {#snippet children()}
          <textarea class="min-h-24" bind:value={form.description} autocomplete="off"></textarea>
        {/snippet}
      </FormField>

      <FormField label="Character">
        {#snippet children()}
          <select bind:value={form.characterId}>
            {#each characters as c (c.id)}
              <option value={c.id}>{characterLabel(c.id)}</option>
            {/each}
          </select>
        {/snippet}
      </FormField>

      <FormField label="Type">
        {#snippet children()}
          <select class="opacity-70" aria-readonly="true" disabled title="Conversation type">
            <option value="direct" selected>direct</option>
          </select>
        {/snippet}
      </FormField>
    </div>
  </div>

  {#if formError}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 font-sans text-sm text-destructive">
      {formError}
    </div>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={cancelChannelFormExplicit}>Cancel</Button>
    <Button disabled={busy} onclick={submitForm}>{formMode === 'create' ? 'Create' : 'Save'}</Button>
  {/snippet}
</Modal>

<Modal
  open={discardConfirmOpen}
  title="Discard changes?"
  overlayClass="z-[60]"
  onClose={keepEditingAfterDismissAttempt}
>
  <p class="font-sans text-sm text-muted-foreground">
    You have unsaved edits for this conversation channel. Discard them or keep editing.
  </p>
  {#snippet footer()}
    <Button variant="outline" onclick={keepEditingAfterDismissAttempt}>Keep editing</Button>
    <Button variant="destructive" onclick={discardUnsavedChannelFormAndClose}>Discard</Button>
  {/snippet}
</Modal>

<Modal
  open={deleteTarget !== null}
  title={`Delete channel '${deleteTarget ? deleteTarget.name : ''}'?`}
  onClose={closeDelete}
>
  <p class="font-sans text-sm text-muted-foreground">All messages in this channel will be removed.</p>
  {#snippet footer()}
    <Button variant="outline" onclick={closeDelete}>Cancel</Button>
    <Button variant="destructive" disabled={busy} onclick={submitDelete}>Delete</Button>
  {/snippet}
</Modal>
