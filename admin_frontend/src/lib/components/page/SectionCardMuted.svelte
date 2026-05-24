<script lang="ts">
  /**
   * Translucent section card used for nested groupings inside another card.
   *
   * Visual variant `ADMIN_SECTION_CARD_MUTED` — deliberately kept distinct
   * from `<SectionCard>` because the two recipes serve different layout
   * roles (top-level grouping vs nested grouping). See
   * `docs/admin-frontend-refactor-plan.md` §2.4.4.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SECTION_CARD_MUTED } from '$lib/styling/admin-tokens';

  type Props = {
    /** Optional extra classes appended to the card. */
    class?: string;
    children?: Snippet;
  };

  let { class: className, children }: Props = $props();
</script>

<div class={cn(ADMIN_SECTION_CARD_MUTED, className)}>
  {@render children?.()}
</div>
