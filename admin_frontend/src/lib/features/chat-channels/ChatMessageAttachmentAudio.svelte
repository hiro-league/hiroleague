<script lang="ts">
  import {
    chatAudioPlaybackRate,
    takeoverChatAudioPlayback,
    releaseChatAudioPlayback
  } from '$lib/features/chat-channels/chat-audio-coordinator';
  import { fetchChatMessageAttachmentBlob, parseMessageAttachmentSlot } from '$lib/api/chat-channels';
  import type { ChatMessageContentItem } from '$lib/api/chat-channels';
  import { Volume2 } from '@lucide/svelte';

  type Props = {
    channelId: number;
    externalMessageId: string;
    audioItem: ChatMessageContentItem;
  };

  let { channelId, externalMessageId, audioItem }: Props = $props();

  let audioUrl = $state<string | null>(null);
  let errorText = $state<string | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);

  $effect(() => {
    let revoked = false;
    let url: string | null = null;
    const slot = parseMessageAttachmentSlot(audioItem.body) ?? 0;
    const optimisticAudioUrl = audioItem.metadata?.optimistic_audio_url;

    if (typeof optimisticAudioUrl === 'string' && optimisticAudioUrl) {
      url = optimisticAudioUrl;
      audioUrl = url;
      return () => {
        revoked = true;
        if (url) URL.revokeObjectURL(url);
      };
    }

    void (async () => {
      try {
        const blob = await fetchChatMessageAttachmentBlob(channelId, externalMessageId, slot);
        url = URL.createObjectURL(blob);
        if (!revoked) {
          audioUrl = url;
        } else {
          URL.revokeObjectURL(url);
        }
      } catch (e) {
        if (!revoked) {
          errorText = e instanceof Error ? e.message : 'Could not load audio.';
        }
      }
    })();

    return () => {
      revoked = true;
      if (url) URL.revokeObjectURL(url);
      audioUrl = null;
      errorText = null;
    };
  });

  $effect(() => {
    const el = audioEl;
    return () => {
      if (el) releaseChatAudioPlayback(el);
    };
  });

  // Apply global playback speed when the toolbar control or `<audio>` node changes.
  $effect(() => {
    const el = audioEl;
    const rate = $chatAudioPlaybackRate;
    if (el) el.playbackRate = rate;
  });

  function onPlay() {
    if (audioEl) takeoverChatAudioPlayback(audioEl);
  }

  function onEnded() {
    if (audioEl) releaseChatAudioPlayback(audioEl);
  }

  const durationLabel = $derived.by(() => {
    const ms = audioItem.metadata?.duration_ms;
    return typeof ms === 'number' && ms > 0 ? `${Math.round(ms / 1000)}s` : null;
  });
</script>

<div class="min-w-0">
  {#if errorText}
    <p class="font-sans text-xs text-destructive/90">{errorText}</p>
  {:else if !audioUrl}
    <span class="inline-flex items-center gap-1 font-sans text-xs opacity-75">
      <Volume2 size={14} aria-hidden="true" /> Loading audio…
    </span>
  {:else}
    <div class="flex min-w-0 items-center gap-2">
      <audio
        class="h-10 min-h-10 min-w-0 max-w-full flex-1 opacity-95"
        bind:this={audioEl}
        controls
        preload="none"
        src={audioUrl}
        title="Message audio"
        onplay={onPlay}
        onended={onEnded}
      ></audio>
      {#if durationLabel}
        <span class="shrink-0 whitespace-nowrap font-sans tabular-nums text-[11px] leading-none opacity-65">
          {durationLabel}
        </span>
      {/if}
    </div>
  {/if}
</div>
