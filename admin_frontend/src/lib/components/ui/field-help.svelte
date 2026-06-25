<script lang="ts">
  /**
   * Small help affordance: a question-mark icon that reveals its text in a hover/focus tooltip.
   * Use next to a field label to keep help text out of the page flow.
   */
  import { Tooltip } from 'bits-ui';
  import CircleHelp from '@lucide/svelte/icons/circle-help';
  import { cn } from '$lib/utils';

  let {
    text,
    label = 'More information',
    class: className = ''
  }: {
    text: string;
    /** Accessible name for the trigger button (screen readers). */
    label?: string;
    class?: string;
  } = $props();
</script>

<Tooltip.Provider delayDuration={150}>
  <Tooltip.Root>
    <Tooltip.Trigger
      type="button"
      aria-label={label}
      onclick={(e) => e.stopPropagation()}
      class={cn(
        'inline-flex size-4 shrink-0 cursor-help items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className
      )}
    >
      <CircleHelp class="size-3.5" aria-hidden="true" />
    </Tooltip.Trigger>
    <Tooltip.Portal>
      <Tooltip.Content
        sideOffset={6}
        class="z-50 max-w-xs rounded-md bg-popover px-2.5 py-1.5 text-xs leading-snug text-popover-foreground shadow-md ring-1 ring-foreground/10"
      >
        {text}
      </Tooltip.Content>
    </Tooltip.Portal>
  </Tooltip.Root>
</Tooltip.Provider>
