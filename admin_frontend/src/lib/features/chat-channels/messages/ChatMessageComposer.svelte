<script lang="ts">
  import { tick } from 'svelte';
  import { Mic, Send, Square } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ChatComposerOptions from '$lib/features/chat-channels/messages/ChatComposerOptions.svelte';
  import type { ChatChannelsPageController } from '$lib/features/chat-channels/state/chat-channels-controller.svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import { ADMIN_TEXTAREA } from '$lib/styling/admin-tokens';
  import { createPoller } from '$lib/state/create-poller.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: ChatChannelsPageController;
    dense: boolean;
    /** Compact overlay renders the options under the toolbar instead of here. */
    compactComposer: boolean;
  };

  let { ctrl, dense, compactComposer }: Props = $props();

  let draftTextareaEl = $state<HTMLTextAreaElement | null>(null);
  let focusedReadyChannelId: string | null = null;

  async function focusDraftTextarea() {
    await tick();
    draftTextareaEl?.focus();
  }

  /** Focus the draft box from the parent (e.g. compact overlay quick-prompt buttons live above this). */
  export function focusDraft() {
    void focusDraftTextarea();
  }

  // Focus the draft box once a channel's messages are ready (not while loading/recording).
  $effect(() => {
    if (
      !ctrl.selectedChannelId ||
      ctrl.messagesLoading ||
      ctrl.composingBusy ||
      ctrl.recordingStartedAt !== null ||
      focusedReadyChannelId === ctrl.selectedChannelId
    ) {
      return;
    }
    focusedReadyChannelId = ctrl.selectedChannelId;
    void focusDraftTextarea();
  });

  async function submitDraftAndRefocus() {
    await ctrl.submitDraftText();
    await focusDraftTextarea();
  }

  async function finalizeRecordingAndRefocus() {
    await ctrl.finalizeRecording();
    await focusDraftTextarea();
  }

  function applyQuickPrompt(text: string) {
    ctrl.draftMessage = text;
    void focusDraftTextarea();
  }

  /** Tick while recording so elapsed seconds update without touching controller state. */
  let recordingNowPerf = $state(0);
  const recordingElapsedPoller = createPoller(
    () => {
      recordingNowPerf = performance.now();
    },
    { intervalMs: 250, immediate: true }
  );
  $effect(() => {
    if (ctrl.recordingStartedAt === null) return;
    recordingNowPerf = performance.now();
    return recordingElapsedPoller.start();
  });

  const recordingElapsedLabel = $derived.by(() => {
    if (ctrl.recordingStartedAt === null) return '';
    const sec = Math.max(0, Math.floor((recordingNowPerf - ctrl.recordingStartedAt) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
  });
</script>

<div class={cn('shrink-0 font-sans text-sm', dense ? 'space-y-1.5' : 'space-y-2 border-border border-t pt-3')}>
  {#if !compactComposer}
    <ChatComposerOptions {ctrl} onPickQuickPrompt={applyQuickPrompt} />
  {/if}
  {#if ctrl.recordingStartedAt !== null}
    <div class="flex flex-wrap items-center gap-3">
      <span class="font-medium text-destructive tabular-nums">
        Recording… {#if recordingElapsedLabel}<span class="opacity-90">({recordingElapsedLabel})</span>{/if}
      </span>
      <Button size="sm" onclick={() => void finalizeRecordingAndRefocus()} disabled={ctrl.composingBusy}>
        <Square size={14} /> Stop & send
      </Button>
      <Button size="sm" variant="outline" onclick={() => void ctrl.discardRecording()} disabled={ctrl.composingBusy}>
        Cancel
      </Button>
    </div>
  {:else}
    <div class={cn('flex gap-2', dense ? 'items-end' : 'items-stretch')}>
      <textarea
        bind:this={draftTextareaEl}
        class={cn(ADMIN_TEXTAREA, 'min-w-0 flex-1 placeholder:text-muted-foreground/40', !dense && 'md:min-w-[16rem]')}
        placeholder="Ask Hiro Anything"
        rows={dense ? 4 : 2}
        bind:value={ctrl.draftMessage}
        onkeydown={(ev) => {
          if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
            ev.preventDefault();
            if (!serverReadiness.ready) return;
            void submitDraftAndRefocus();
            return;
          }
          if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            if (!serverReadiness.ready) return;
            void submitDraftAndRefocus();
          }
        }}
        disabled={ctrl.composingBusy}
      ></textarea>
      <Button
        class="h-11 min-w-11 self-stretch px-0"
        title={serverReadiness.ready
          ? 'Send message (Enter)'
          : 'HiroServer is still starting — send will be available momentarily.'}
        disabled={ctrl.composingBusy || !ctrl.draftMessage.trim() || !serverReadiness.ready}
        onclick={() => void submitDraftAndRefocus()}
      >
        <Send size={20} />
      </Button>
      <Button
        variant="destructive-outline"
        class="h-11 min-w-11 shrink-0 self-stretch px-0"
        title="Record voice message"
        disabled={ctrl.composingBusy}
        aria-label="Record voice message"
        onclick={() => void ctrl.beginRecording()}
      >
        <Mic size={20} strokeWidth={2.25} class="text-destructive" />
      </Button>
    </div>
  {/if}
</div>
