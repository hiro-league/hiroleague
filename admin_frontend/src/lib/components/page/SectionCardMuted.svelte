<script lang="ts">
  /**
   * Translucent section card used for nested groupings inside another card.
   *
   * Optional `collapsible` mode adds a chevron header toggle; the body stays in
   * the DOM with `hidden` (see svelte-best-practice §10 / §11.3).
   */
  import type { Snippet } from 'svelte';
  import { getContext, hasContext, onMount, untrack } from 'svelte';
  import { ChevronRight } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import { ADMIN_SECTION_CARD_MUTED } from '$lib/styling/admin-tokens';
  import {
    COLLAPSIBLE_SECTION_REGISTRY,
    type CollapsibleSectionRegistry
  } from './collapsible-section-registry.svelte';

  type Props = {
    /** Section heading; required when `collapsible` is true. */
    title?: string;
    /** Intro copy shown inside the expanded body. */
    description?: string;
    /** When true, render `description` as a help icon + tooltip next to the title (matches field hints) instead of as a paragraph. */
    descriptionTooltip?: boolean;
    /** When true (collapsible only), indent the body so it lines up with the title text, not the chevron. */
    indentBody?: boolean;
    /** When true, `bodyId` is required and the body can be collapsed. */
    collapsible?: boolean;
    defaultExpanded?: boolean;
    /** Controlled region id for `aria-controls` — required when `collapsible`. */
    bodyId?: string;
    /** Optional explicit registry; otherwise reads `COLLAPSIBLE_SECTION_REGISTRY` context. */
    collapseRegistry?: CollapsibleSectionRegistry;
    class?: string;
    /** Trailing header actions (badges, buttons) outside the collapse toggle. */
    headerActions?: Snippet;
    children?: Snippet;
  };

  let {
    title,
    description,
    descriptionTooltip = false,
    indentBody = false,
    collapsible = false,
    defaultExpanded = true,
    bodyId,
    collapseRegistry,
    class: className,
    headerActions,
    children
  }: Props = $props();

  let expanded = $state(untrack(() => defaultExpanded));

  const contextRegistry = hasContext(COLLAPSIBLE_SECTION_REGISTRY)
    ? getContext<CollapsibleSectionRegistry>(COLLAPSIBLE_SECTION_REGISTRY)
    : undefined;
  const registry = $derived(collapseRegistry ?? contextRegistry);

  onMount(() => {
    if (!collapsible || !registry) return;
    return registry.register({
      getExpanded: () => expanded,
      setExpanded: (next) => {
        expanded = next;
      }
    });
  });

  function toggleExpanded() {
    expanded = !expanded;
    registry?.notifyChanged();
  }
</script>

<div class={cn(ADMIN_SECTION_CARD_MUTED, 'grid gap-3', className)}>
  {#if title}
    {#if collapsible}
      <div class="flex items-start justify-between gap-2">
        <!-- FieldHelp (a button) must sit OUTSIDE the toggle button, so the title/help live in a
             flex-1 row and the toggle button shrinks to its content. -->
        <div class="flex min-w-0 flex-1 items-start gap-1.5">
          <button
            type="button"
            class="flex min-w-0 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={expanded}
            aria-controls={bodyId}
            onclick={toggleExpanded}
          >
            <ChevronRight
              size={18}
              class={cn(
                'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
                expanded && 'rotate-90'
              )}
              aria-hidden="true"
            />
            <span class="font-sans text-base font-semibold text-primary">{title}</span>
          </button>
          {#if description && descriptionTooltip}
            <FieldHelp text={description} class="mt-1.5" />
          {/if}
        </div>
        {#if headerActions}
          <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {@render headerActions()}
          </div>
        {/if}
      </div>
      <div
        id={bodyId}
        class={cn('grid gap-3', indentBody && 'pl-[26px]')}
        hidden={!expanded}
      >
        {#if description && !descriptionTooltip}
          <p class="text-sm text-muted-foreground">{description}</p>
        {/if}
        {@render children?.()}
      </div>
    {:else}
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 grid gap-1">
          <div class="flex items-center gap-1.5">
            <h4 class="font-sans text-base font-semibold text-primary">{title}</h4>
            {#if description && descriptionTooltip}
              <FieldHelp text={description} />
            {/if}
          </div>
          {#if description && !descriptionTooltip}
            <p class="text-sm text-muted-foreground">{description}</p>
          {/if}
        </div>
        {#if headerActions}
          <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {@render headerActions()}
          </div>
        {/if}
      </div>
      {@render children?.()}
    {/if}
  {:else}
    {@render children?.()}
  {/if}
</div>
