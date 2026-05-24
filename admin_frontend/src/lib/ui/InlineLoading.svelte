<script lang="ts">
  /**
   * Single canonical inline "loading" placeholder.
   *
   * Replaces ad-hoc `<p class="text-muted-foreground">Loading…</p>` blocks
   * scattered across pages.
   */
  import { cn } from '$lib/utils';

  type Props = {
    /** Override the default "Loading…" copy. */
    label?: string;
    /** Optional extra classes appended to the wrapper. */
    class?: string;
  };

  let { label = 'Loading\u2026', class: className }: Props = $props();
</script>

<p
  class={cn('font-sans text-sm text-muted-foreground', className)}
  role="status"
  aria-live="polite"
>
  {label}
</p>
