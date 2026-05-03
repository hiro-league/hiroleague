<script lang="ts">
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { cn } from '$lib/utils';

  let {
    editorLabel,
    previewLabel,
    ariaLabel,
    value = $bindable(''),
    onInput
  }: {
    editorLabel: string;
    previewLabel: string;
    ariaLabel: string;
    value?: string;
    /** Called after each keystroke so parents can mark the form dirty. */
    onInput?: () => void;
  } = $props();
</script>

<div class="grid gap-3">
  <div class="grid gap-2 lg:grid-cols-2 lg:items-end lg:gap-6">
    <span class="font-sans text-[0.9375rem] font-semibold text-foreground">{editorLabel}</span>
    <span class="font-sans text-[0.9375rem] font-semibold text-foreground">{previewLabel}</span>
  </div>
  <div class="grid gap-4 lg:grid-cols-2 lg:items-start">
    <textarea
      class={cn(
        'w-full min-h-[18rem] resize-y rounded-lg border-2 border-input',
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
    <div class="rounded-lg border-2 border-primary/20 bg-card p-4 text-sm shadow-sm">
      <MarkdownPreview markdown={value} compact />
    </div>
  </div>
</div>
