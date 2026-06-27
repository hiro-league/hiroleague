<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { cn } from '$lib/utils';

  let {
    editorLabel,
    previewLabel,
    ariaLabel,
    value = $bindable(''),
    defaultValue,
    onInput,
    minHeightClass = 'min-h-[18rem]'
  }: {
    editorLabel: string;
    previewLabel: string;
    ariaLabel: string;
    value?: string;
    /**
     * Built-in default text for this prompt. When provided, a "Restore default" button fills the
     * editor with it — needed because a cleared prompt persists "" and the backend default only
     * applies to absent keys, so the UI otherwise shows blank forever with no way back.
     */
    defaultValue?: string;
    /** Called after each keystroke so parents can mark the form dirty. */
    onInput?: () => void;
    /** Min-height utility for the editor + preview panes (taller inside the prompt dialog). */
    minHeightClass?: string;
  } = $props();

  const isAtDefault = $derived(defaultValue !== undefined && value === defaultValue);

  function restoreDefault() {
    if (defaultValue === undefined) return;
    value = defaultValue;
    // Restore is an edit like any other — let the parent mark the form dirty so Save persists it.
    onInput?.();
  }
</script>

<div class="grid gap-3">
  <div class="grid gap-2 lg:grid-cols-2 lg:items-end lg:gap-6">
    <div class="flex items-center justify-between gap-3">
      <span class="font-sans text-[0.9375rem] font-semibold text-foreground">{editorLabel}</span>
      {#if defaultValue !== undefined}
        <Button
          variant="outline"
          size="sm"
          disabled={isAtDefault}
          title={isAtDefault
            ? 'Editor already matches the built-in default.'
            : 'Replace the editor content with the built-in default prompt. Takes effect on Save.'}
          onclick={restoreDefault}
        >
          Restore default
        </Button>
      {/if}
    </div>
    <span class="font-sans text-[0.9375rem] font-semibold text-foreground">{previewLabel}</span>
  </div>
  <div class="grid gap-4 lg:grid-cols-2 lg:items-start">
    <textarea
      class={cn(
        'w-full resize-y rounded-lg border-2 border-input',
        minHeightClass,
        'bg-[color-mix(in_oklab,var(--muted)_45%,var(--background))] px-4 py-3 font-mono text-sm leading-relaxed',
        'text-foreground shadow-[inset_0_1px_2px_rgb(0_0_0_/_0.06)] outline-none transition-[border-color,box-shadow]',
        'hover:border-[color-mix(in_oklab,var(--primary)_35%,var(--input))]',
        'focus-visible:border-ring focus-visible:shadow-[inset_0_1px_2px_rgb(0_0_0_/_0.06),0_0_0_3px_color-mix(in_oklab,var(--ring)_35%,transparent)]'
      )}
      spellcheck="true"
      aria-label={ariaLabel}
      bind:value
      oninput={() => onInput?.()}
    ></textarea>
    <div
      class={cn(
        'overflow-auto rounded-lg border-2 border-primary/20 bg-card p-4 text-sm shadow-sm',
        minHeightClass
      )}
    >
      <MarkdownPreview markdown={value} compact />
    </div>
  </div>
</div>
