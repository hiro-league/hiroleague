<script lang="ts">
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { Edit, MessageSquare, Plus, RefreshCw, Trash2 } from '@lucide/svelte';
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';

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

  const CHAT_CHANNELS_GRID =
    '72px minmax(0,1fr) 90px minmax(0,1.1fr) minmax(0,1fr) 160px 150px';

  const view = $derived({
    data: channels.length || !(channelsLoading || channelsError) ? channels : null,
    error: channelsError ?? '',
    loading: channelsLoading,
    reload: () => onRefresh()
  });
</script>

<Panel title="Channels" description={`${channels.length} conversation threads`}>
  {#snippet actions()}
    <Button variant="outline" onclick={onRefresh}><RefreshCw size={15} /> Refresh</Button>
    <Button onclick={onAddChannel}><Plus size={15} /> Add channel</Button>
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading chat channels…"
    errorTitle="Could not load chat channels"
    empty={(d) => d.length === 0}
    emptyMessage="No conversation channels yet."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={1120} gridColumns={CHAT_CHANNELS_GRID}>
        {#snippet headRow()}
          <span>ID</span>
          <span>Name</span>
          <span>Type</span>
          <span>Description</span>
          <span>Character</span>
          <span>Last activity</span>
          <span>Actions</span>
        {/snippet}
        {#snippet body()}
          {#each channels as row (row.id)}
            <div class={TABLE_GRID_ROW} style:grid-template-columns={CHAT_CHANNELS_GRID}>
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
        {/snippet}
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
