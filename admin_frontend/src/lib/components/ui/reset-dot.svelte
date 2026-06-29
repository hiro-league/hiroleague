<script lang="ts">
  /**
   * Small "reset to default" affordance: a rotate-ccw icon button placed next to a field label
   * when the field's value differs from its built-in default. Mirrors `FieldHelp`'s sizing and
   * label-row placement (the two sit side by side: `label (?) (↺)`).
   *
   * This is JUST the button — the caller decides WHEN to render it (i.e. only when the value is
   * non-default). `onclick` stops propagation so a dot living inside a `<label>` never activates
   * the labelled control (same pattern as `FieldHelp`).
   */
  import { RotateCcw } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  let {
    onReset,
    label = 'Reset to default',
    class: className = ''
  }: {
    onReset: () => void;
    /** Accessible name / tooltip for the trigger. */
    label?: string;
    class?: string;
  } = $props();
</script>

<button
  type="button"
  aria-label={label}
  title={label}
  onclick={(e) => {
    e.stopPropagation();
    onReset();
  }}
  class={cn(
    'inline-flex size-4 shrink-0 cursor-pointer items-center justify-center rounded text-muted-foreground/60 transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
    className
  )}
>
  <RotateCcw class="size-3.5" aria-hidden="true" />
</button>
