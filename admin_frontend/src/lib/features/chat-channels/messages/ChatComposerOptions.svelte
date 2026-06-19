<script lang="ts">
  import type { ChatChannelsPageController } from '$lib/features/chat-channels/state/chat-channels-controller.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: ChatChannelsPageController;
    /** Fill the draft box with a sample prompt (panel keeps focus management). */
    onPickQuickPrompt: (text: string) => void;
  };

  let { ctrl, onPickQuickPrompt }: Props = $props();

  /** Sample prompts — click a number to replace the draft box (voice-reply UX smoke tests). */
  const QUICK_PROMPT_TEMPLATES = [
    'What is the capital of Spain? Reply with one word only.',
    'Who experimented with lightning and electricity using a kite (full name)? Reply with one sentence only.',
    'What is 8 × 7? Reply with one word only.',
    'What is photosynthesis in one sentence only?',
    'Name a gas we breathe out. Reply with one word only.'
  ] as const;
</script>

<div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
  <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
    <label
      class={cn(
        'flex items-center gap-2 text-xs text-muted-foreground',
        ctrl.voiceReplyCheckboxDisabled ? 'cursor-not-allowed opacity-80' : 'cursor-pointer'
      )}
      title={ctrl.voiceReplyCheckboxHint ||
        'Ask the agent to reply with synthesized speech (same as mobile routing flag).'}
    >
      <input
        type="checkbox"
        bind:checked={ctrl.requestVoiceReplyUi}
        disabled={ctrl.voiceReplyCheckboxDisabled}
        class="accent-primary h-4 w-4 shrink-0 disabled:cursor-not-allowed"
      />
      Get voice reply
    </label>
    <label
      class="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground"
      title="Augment this message's reply with relevant workspace knowledge (sent per-message)."
    >
      <input type="checkbox" bind:checked={ctrl.useKnowledgeUi} class="accent-primary h-4 w-4 shrink-0" />
      Use knowledge
    </label>
    <label
      class="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground"
      title="Disable agent tools for this message (overrides the global chat tools preference)."
    >
      <input type="checkbox" bind:checked={ctrl.disableToolsUi} class="accent-primary h-4 w-4 shrink-0" />
      Disable tools
    </label>
  </div>
  <div class="flex shrink-0 items-center gap-1" role="group" aria-label="Fill message box with a sample prompt">
    {#each QUICK_PROMPT_TEMPLATES as prompt, i (i)}
      <button
        type="button"
        class="grid size-8 place-items-center rounded border border-input bg-background font-sans text-xs font-semibold tabular-nums text-muted-foreground shadow-xs transition-colors hover:border-primary/50 hover:bg-primary/10 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        title={prompt}
        aria-label={`Sample prompt ${i + 1}: ${prompt}`}
        disabled={ctrl.composingBusy}
        onclick={() => onPickQuickPrompt(prompt)}
      >
        {i + 1}
      </button>
    {/each}
  </div>
</div>
{#if ctrl.voiceReplyCheckboxDisabled && ctrl.voiceReplyCheckboxHint}
  <p class="max-w-prose text-[11px] leading-snug text-muted-foreground">
    {ctrl.voiceReplyCheckboxHint}
  </p>
{/if}
