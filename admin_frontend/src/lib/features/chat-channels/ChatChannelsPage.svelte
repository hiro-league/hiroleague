<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Edit, MessageSquare, Plus, RefreshCw, Trash2 } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import {
    createChatChannel,
    deleteChatChannel,
    listChatChannels,
    listChatMessages,
    updateChatChannel,
    type ChatChannelPayload,
    type ChatChannelRow,
    type ChatMessageRow
  } from '$lib/api/chat-channels';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { PREF_KEYS, type ChatChannelsTabPreference } from '$lib/preferences/keys';
  import { readSessionString, writeSessionString } from '$lib/preferences/storage';
  import Modal from '$lib/ui/Modal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { cn } from '$lib/utils';

  type NotifyKind = 'success' | 'error' | 'info' | 'warning';

  let toast = $state<{ kind: NotifyKind; message: string } | null>(null);
  let activeTab = $state<ChatChannelsTabPreference>('channels');
  let selectedChannelId = $state<string | null>(null);
  let channels = $state<ChatChannelRow[]>([]);
  let messages = $state<ChatMessageRow[]>([]);
  let channelsLoading = $state(true);
  let messagesLoading = $state(false);
  let channelsError = $state<string | null>(null);
  let messagesError = $state<string | null>(null);
  let busy = $state(false);
  let formOpen = $state(false);
  let formMode = $state<'create' | 'edit'>('create');
  let editingChannelId = $state<number | null>(null);
  let formError = $state<string | null>(null);
  let form = $state({
    name: '',
    userId: '',
    characterId: '',
    channelType: 'direct'
  });
  let deleteTarget = $state<ChatChannelRow | null>(null);

  const selectedChannel = $derived(
    selectedChannelId
      ? (channels.find((channel) => String(channel.id) === selectedChannelId) ?? null)
      : null
  );
  const formTitle = $derived(
    formMode === 'create' ? 'New conversation channel' : 'Edit conversation channel'
  );

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

  function formatDate(value: string | null | undefined) {
    return value ? value.replace('T', ' ').replace('Z', ' UTC') : '-';
  }

  function senderMeta(message: ChatMessageRow) {
    const senderType = message.sender_type || 'unknown';
    return message.sender_id ? `${senderType} · ${message.sender_id}` : senderType;
  }

  function openCreate() {
    formMode = 'create';
    editingChannelId = null;
    formError = null;
    form = { name: '', userId: '', characterId: '', channelType: 'direct' };
    formOpen = true;
  }

  function openEdit(row: ChatChannelRow) {
    formMode = 'edit';
    editingChannelId = row.id;
    formError = null;
    form = {
      name: row.name,
      userId: String(row.user_id),
      characterId: row.character_id,
      channelType: row.type || 'direct'
    };
    formOpen = true;
  }

  function closeForm() {
    if (busy) return;
    formOpen = false;
  }

  function parseForm(): ChatChannelPayload | null {
    const name = form.name.trim();
    const characterId = form.characterId.trim();
    const userId = Number.parseInt(form.userId, 10);
    const channelType = form.channelType.trim() || 'direct';

    if (!name || !characterId || !Number.isInteger(userId) || userId < 1) {
      formError = 'Name, User ID (>= 1), and Character ID are required.';
      return null;
    }

    return {
      name,
      user_id: userId,
      character_id: characterId,
      channel_type: channelType
    };
  }

  async function submitForm() {
    const payload = parseForm();
    if (!payload) return;

    busy = true;
    formError = null;
    try {
      if (formMode === 'edit' && editingChannelId !== null) {
        await updateChatChannel(editingChannelId, payload);
        notify('success', 'Channel updated.');
      } else {
        await createChatChannel(payload);
        notify('success', 'Channel created.');
      }
      formOpen = false;
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

  onMount(async () => {
    initializeNavigation();
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
          <div class="min-w-[1060px]">
            <div
              class="grid grid-cols-[72px_1.1fr_120px_1fr_100px_180px_150px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground"
            >
              <span>ID</span>
              <span>Name</span>
              <span>Type</span>
              <span>Character</span>
              <span>User</span>
              <span>Last activity</span>
              <span>Actions</span>
            </div>
            {#each channels as row (row.id)}
              <div
                class="grid min-h-16 grid-cols-[72px_1.1fr_120px_1fr_100px_180px_150px] gap-3 border-t px-3 py-3"
              >
                <span class="font-mono text-xs text-muted-foreground">{row.id}</span>
                <span class="truncate font-sans text-sm font-semibold" title={row.name}>{row.name}</span>
                <span><Badge variant="secondary">{row.type || 'direct'}</Badge></span>
                <span class="truncate font-mono text-xs text-muted-foreground" title={row.character_id}>
                  {row.character_id}
                </span>
                <span class="font-mono text-xs text-muted-foreground">{row.user_id}</span>
                <span class="truncate text-xs text-muted-foreground">{formatDate(row.last_message_at)}</span>
                <span class="flex justify-end gap-1">
                  <Button size="icon" variant="ghost" onclick={() => openMessages(row)} title="Messages">
                    <MessageSquare size={15} />
                  </Button>
                  <Button size="icon" variant="ghost" onclick={() => openEdit(row)} title="Edit">
                    <Edit size={15} />
                  </Button>
                  <Button size="icon" variant="ghost" onclick={() => (deleteTarget = row)} title="Delete">
                    <Trash2 size={15} />
                  </Button>
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {:else}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Messages</h3>
          <span class="font-sans text-sm text-muted-foreground">
            {#if selectedChannel}
              Channel: {selectedChannel.name} (id {selectedChannel.id})
            {:else}
              No channel selected
            {/if}
          </span>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          {#if channels.length > 0}
            <select
              class="h-9 min-w-56 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              bind:value={selectedChannelId}
              onchange={handleChannelSelect}
              aria-label="Message channel"
            >
              {#each channels as channel (channel.id)}
                <option value={String(channel.id)}>{channel.name} (id {channel.id})</option>
              {/each}
            </select>
          {/if}
          <Button variant="outline" onclick={refreshCurrent}><RefreshCw size={15} /> Refresh</Button>
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
        <p class="text-muted-foreground">No conversation channels. Create one on the Channels tab.</p>
      {:else if messagesLoading}
        <p class="text-muted-foreground">Loading messages...</p>
      {:else if messagesError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load messages</strong>
          <span class="block text-sm">{messagesError}</span>
        </div>
      {:else if messages.length === 0}
        <p class="text-muted-foreground">No messages in this channel yet.</p>
      {:else}
        <div class="max-h-[70vh] overflow-y-auto rounded-md border bg-background/45 p-4">
          <div class="grid max-w-3xl gap-3">
            {#each messages as message (message.id)}
              {@const isUser = message.sender_type === 'user'}
              <div class={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
                <div
                  class={cn(
                    'grid max-w-[85%] gap-1 rounded-2xl px-4 py-2 shadow-sm',
                    isUser ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'
                  )}
                >
                  <p class="whitespace-pre-wrap break-words font-sans text-sm">
                    {message.body || 'No text body'}
                  </p>
                  <span class="font-sans text-xs opacity-70">{senderMeta(message)}</span>
                  {#if message.created_at}
                    <span class="font-sans text-xs opacity-50">{formatDate(message.created_at)}</span>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {/if}
</section>

<ToastHost {toast} />

<Modal open={formOpen} title={formTitle} onClose={closeForm}>
  <label>
    Name
    <input bind:value={form.name} autocomplete="off" />
  </label>
  <label>
    User ID
    <input bind:value={form.userId} inputmode="numeric" autocomplete="off" />
  </label>
  <label>
    Character ID
    <input bind:value={form.characterId} autocomplete="off" />
  </label>
  <label>
    Type
    <input bind:value={form.channelType} autocomplete="off" />
  </label>
  {#if formError}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 font-sans text-sm text-destructive">
      {formError}
    </div>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={closeForm}>Cancel</Button>
    <Button disabled={busy} onclick={submitForm}>{formMode === 'create' ? 'Create' : 'Save'}</Button>
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
