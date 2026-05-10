<script lang="ts">
  import { Edit, MessageSquare, Plus, RefreshCw, Trash2 } from '@lucide/svelte';
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import InlineDestructiveAlert from '$lib/features/chat-channels/shared/InlineDestructiveAlert.svelte';
  import MutedStatusLine from '$lib/features/chat-channels/shared/MutedStatusLine.svelte';
  import {
    chatChannelsTableDataRowClass,
    chatChannelsTableHeaderRowClass
  } from '$lib/features/chat-channels/shared/chat-channel-table-classes';

  type Props = {
    channels: ChatChannelRow[];
    channelsLoading: boolean;
    channelsError: string | null;
    onRefresh: () => void;
    onAddChannel: () => void;
    onOpenMessages: (row: ChatChannelRow) => void;
    onEditChannel: (row: ChatChannelRow) => void;
    onDeleteChannel: (row: ChatChannelRow) => void;
  };

  let {
    channels,
    channelsLoading,
    channelsError,
    onRefresh,
    onAddChannel,
    onOpenMessages,
    onEditChannel,
    onDeleteChannel
  }: Props = $props();
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Channels</h3>
      <span class="font-sans text-sm text-muted-foreground">{channels.length} conversation threads</span>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button variant="outline" onclick={onRefresh}
        ><RefreshCw size={15} /> Refresh</Button
      >
      <Button onclick={onAddChannel}><Plus size={15} /> Add channel</Button>
    </div>
  </div>

  {#if channelsLoading}
    <MutedStatusLine text="Loading chat channels..." />
  {:else if channelsError}
    <InlineDestructiveAlert title="Could not load chat channels" message={channelsError} />
  {:else if channels.length === 0}
    <MutedStatusLine text="No conversation channels yet." />
  {:else}
    <div class="overflow-x-auto rounded-md border">
      <div class="min-w-[1120px]">
        <div class={chatChannelsTableHeaderRowClass}>
          <span>ID</span>
          <span>Name</span>
          <span>Type</span>
          <span>Description</span>
          <span>Character</span>
          <span>Last activity</span>
          <span>Actions</span>
        </div>
        {#each channels as row (row.id)}
          <div class={chatChannelsTableDataRowClass}>
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
              <Button size="icon" variant="ghost" onclick={() => onOpenMessages(row)} title="Messages">
                <MessageSquare size={15} />
              </Button>
              <Button size="icon" variant="ghost" onclick={() => onEditChannel(row)} title="Edit">
                <Edit size={15} />
              </Button>
              {#if !row.is_lowest_id_channel}
                <Button
                  size="icon"
                  variant="ghost"
                  onclick={() => onDeleteChannel(row)}
                  title="Delete"
                >
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
