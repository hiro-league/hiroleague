<script lang="ts">
  import { BarChart3, FileX2, ImageIcon, RefreshCw, Wrench } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import {
    cycleChatAudioSpeed,
    formatChatAudioSpeedLabel,
    chatAudioPlaybackRate
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import type { ChatChannelsPageController } from '$lib/features/chat-channels/state/chat-channels-controller.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: ChatChannelsPageController;
    dense: boolean;
    onChannelChange: () => void | Promise<void>;
    onRefresh: () => void | Promise<void>;
  };

  let { ctrl, dense, onChannelChange, onRefresh }: Props = $props();

  const audioSpeedLabel = $derived(formatChatAudioSpeedLabel($chatAudioPlaybackRate));
</script>

<div class="flex shrink-0 min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
  {#if !dense}
    <div class="flex min-w-0 items-center gap-3">
      {#if ctrl.messagesHeaderPhotoSrc}
        <img
          src={ctrl.messagesHeaderPhotoSrc}
          alt=""
          class="size-14 shrink-0 rounded-xl border bg-muted object-cover"
          title={ctrl.messagesHeaderChannelHint}
        />
      {:else}
        <div
          class="flex size-14 shrink-0 items-center justify-center rounded-xl border border-dashed bg-muted text-muted-foreground"
          aria-hidden="true"
          title={ctrl.messagesHeaderChannelHint}
        >
          <ImageIcon size={24} />
        </div>
      {/if}
      <div class="min-w-0">
        <h3 class="truncate text-lg font-semibold leading-tight" title={ctrl.messagesHeaderChannelHint}>
          {ctrl.messagesHeaderChannelName ?? 'Messages'}
        </h3>
        {#if ctrl.selectedChannelExists && ctrl.messagesHeaderCharacterName}
          <p class="mt-0.5 truncate font-sans text-sm leading-tight" title={ctrl.messagesHeaderChannelHint}>
            <span class="font-semibold text-foreground">{ctrl.messagesHeaderCharacterName}</span>
            {#if ctrl.messagesHeaderDeviceId}
              <span class="text-muted-foreground"> · </span>
              <span class="font-mono text-[11px] text-muted-foreground">{ctrl.messagesHeaderDeviceId}</span>
            {/if}
          </p>
        {:else}
          <span class="mt-0.5 block font-sans text-sm text-muted-foreground">No channel selected</span>
        {/if}
      </div>
    </div>
  {/if}
  <div class={cn('flex flex-wrap items-center gap-2', dense ? 'w-full' : 'shrink-0')}>
    {#if ctrl.channels.length > 0}
      <select
        class={cn(ADMIN_SELECT, dense ? 'w-full' : 'min-w-56')}
        bind:value={ctrl.selectedChannelId}
        onchange={() => onChannelChange()}
        aria-label="Message channel"
        title={ctrl.messagesHeaderChannelHint}
      >
        {#each ctrl.channels as channel (channel.id)}
          <option value={String(channel.id)}>{channel.name} (id {channel.id})</option>
        {/each}
      </select>
    {/if}
    <Button
      variant="outline"
      size="icon"
      class="border-destructive/60 text-destructive hover:bg-destructive/10"
      disabled={ctrl.busy || !ctrl.selectedChannelId || ctrl.channelsLoading}
      onclick={() => ctrl.openClearMessagesModal()}
      aria-label="Clear channel"
      title="Remove all messages in this channel"
    >
      <FileX2 size={15} />
    </Button>
    <Button variant="outline" onclick={cycleChatAudioSpeed} title="Cycle playback speed (applies to all clips)">
      {audioSpeedLabel}
    </Button>
    <Button
      variant="outline"
      size="icon"
      class={cn(!ctrl.showAgentTokensUi && 'opacity-50')}
      aria-label={ctrl.showAgentTokensUi ? 'Hide message stats' : 'Show message stats'}
      aria-pressed={ctrl.showAgentTokensUi}
      title={ctrl.showAgentTokensUi ? 'Hide token & cost stats' : 'Show token & cost stats'}
      onclick={() => {
        ctrl.showAgentTokensUi = !ctrl.showAgentTokensUi;
      }}
    >
      <BarChart3 size={15} />
    </Button>
    <Button
      variant="outline"
      size="icon"
      class={cn(!ctrl.showAgentToolsUi && 'opacity-50')}
      aria-label={ctrl.showAgentToolsUi ? 'Hide message tools' : 'Show message tools'}
      aria-pressed={ctrl.showAgentToolsUi}
      title={ctrl.showAgentToolsUi ? 'Hide tool stack' : 'Show tool stack'}
      onclick={() => {
        ctrl.showAgentToolsUi = !ctrl.showAgentToolsUi;
      }}
    >
      <Wrench size={15} />
    </Button>
    <Button
      variant="outline"
      size="icon"
      aria-label="Refresh messages"
      title="Refresh messages"
      onclick={() => onRefresh()}
    >
      <RefreshCw size={15} />
    </Button>
  </div>
</div>
