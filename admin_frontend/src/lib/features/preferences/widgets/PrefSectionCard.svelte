<script lang="ts">
  /**
   * `SectionCardMuted` for the Settings page that auto-hides when the "show advanced" toggle leaves
   * it with no visible fields. It provides a per-card `PrefFieldRegistry` (each enclosed `Pref*Field`
   * registers a visibility probe) and applies `hidden` to the card root once every field is hidden.
   *
   * Cards that contain no gated fields (e.g. only prompt editors or custom rows) never auto-hide:
   * the registry's `hasFields` stays false. Children stay mounted while hidden so their probes keep
   * reporting — only the card's visual chrome collapses.
   */
  import type { Snippet } from 'svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import { cn } from '$lib/utils';
  import {
    createPrefFieldRegistry,
    providePrefFieldRegistry
  } from '$lib/features/preferences/shared/preferences-advanced.svelte';

  type Props = {
    title?: string;
    description?: string;
    collapsible?: boolean;
    defaultExpanded?: boolean;
    bodyId?: string;
    class?: string;
    headerActions?: Snippet;
    children?: Snippet;
  };

  let { class: className, headerActions, children, ...rest }: Props = $props();

  const registry = createPrefFieldRegistry();
  providePrefFieldRegistry(registry);

  // Hide only once fields have registered AND none are visible — never collapse a card that has no
  // gated fields to begin with.
  const hidden = $derived(registry.hasFields && !registry.anyVisible);
</script>

<SectionCardMuted {...rest} {headerActions} class={cn(className, hidden && 'hidden')}>
  {@render children?.()}
</SectionCardMuted>
