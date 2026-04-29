<script lang="ts">
  import { X } from '@lucide/svelte';
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';

  let {
    open,
    title,
    subtitle = '',
    children,
    footer,
    onClose
  }: {
    open: boolean;
    title: string;
    subtitle?: string;
    children?: Snippet;
    footer?: Snippet;
    onClose: () => void;
  } = $props();
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 grid place-items-center bg-background/70 p-4 backdrop-blur-sm"
    role="presentation"
    onclick={onClose}
  >
    <div
      class="grid max-h-[calc(100vh-2rem)] w-full max-w-xl overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-2xl"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <header class="flex items-start justify-between gap-4 border-b px-5 py-4">
        <div class="min-w-0 space-y-1">
          <h2 class="truncate font-sans text-lg font-semibold leading-none">{title}</h2>
          {#if subtitle}
            <p class="truncate font-sans text-sm text-muted-foreground">{subtitle}</p>
          {/if}
        </div>
        <Button aria-label="Close dialog" class="size-8" variant="ghost" size="icon" onclick={onClose}>
          <X size={16} />
        </Button>
      </header>
      <div
        class="grid gap-4 overflow-y-auto p-5 [&_.check-row]:!flex [&_.check-row]:items-center [&_.check-row]:gap-2 [&_details]:grid [&_details]:gap-3 [&_details]:rounded-md [&_details]:border [&_details]:bg-muted/40 [&_details]:p-3 [&_input]:min-h-9 [&_input]:rounded-md [&_input]:border [&_input]:border-input [&_input]:bg-background [&_input]:px-3 [&_input]:py-2 [&_input]:font-sans [&_input]:text-sm [&_input]:outline-none [&_input]:focus-visible:ring-2 [&_input]:focus-visible:ring-ring [&_label]:grid [&_label]:gap-1.5 [&_label]:font-sans [&_label]:text-sm [&_label]:font-medium [&_label]:text-muted-foreground [&_summary]:cursor-pointer [&_summary]:font-sans [&_summary]:font-semibold [&_textarea]:min-h-28 [&_textarea]:w-full [&_textarea]:rounded-md [&_textarea]:border [&_textarea]:border-input [&_textarea]:bg-background [&_textarea]:px-3 [&_textarea]:py-2 [&_textarea]:font-serif [&_textarea]:text-sm [&_textarea]:outline-none [&_textarea]:focus-visible:ring-2 [&_textarea]:focus-visible:ring-ring"
      >
        {@render children?.()}
      </div>
      {#if footer}
        <footer class="flex justify-end gap-2 border-t bg-muted/40 px-5 py-4">
          {@render footer()}
        </footer>
      {/if}
    </div>
  </div>
{/if}
