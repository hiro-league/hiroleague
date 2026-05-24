<script lang="ts">
  /**
   * Solid section card used to group page-level sections.
   *
   * Visual variant `ADMIN_SECTION_CARD` (solid `bg-card`). See
   * `<SectionCardMuted>` for the translucent nested-card variant —
   * `docs/admin-frontend-refactor-plan.md` §2.4.4.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SECTION_CARD } from '$lib/styling/admin-tokens';

  type Props = {
    /** Optional extra classes appended to the card. */
    class?: string;
    children?: Snippet;
  };

  let { class: className, children }: Props = $props();
</script>

<div class={cn(ADMIN_SECTION_CARD, className)}>
  {@render children?.()}
</div>
