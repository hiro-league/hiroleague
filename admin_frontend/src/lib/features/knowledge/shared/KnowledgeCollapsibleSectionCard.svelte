<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import { ChevronRight } from '@lucide/svelte';
  import { KNOWLEDGE_SECTION_CARD, KNOWLEDGE_SECTION_TITLE } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  type Props = {
    title: string;
    /** Stable id for `aria-controls` — body stays in the DOM with `hidden`. */
    bodyId: string;
    defaultExpanded?: boolean;
    /** Optional trailing header summary (visible expanded or collapsed). */
    summary?: string;
    /** Optional trailing header summary shown ONLY while collapsed (e.g. the
     *  current activity line, so a collapsed feed still tells you where it's at). */
    collapsedSummary?: string;
    headerActions?: Snippet;
    children?: Snippet;
  };

  let {
    title,
    bodyId,
    defaultExpanded = true,
    summary,
    collapsedSummary,
    headerActions,
    children
  }: Props = $props();

  let expanded = $state(untrack(() => defaultExpanded));
</script>

<section class={KNOWLEDGE_SECTION_CARD}>
  <div class="grid gap-3">
    <div class="flex items-start justify-between gap-2">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={expanded}
        aria-controls={bodyId}
        onclick={() => {
          expanded = !expanded;
        }}
      >
        <ChevronRight
          size={18}
          class={cn(
            'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
            expanded && 'rotate-90'
          )}
          aria-hidden="true"
        />
        <span class={KNOWLEDGE_SECTION_TITLE}>{title}</span>
      </button>
      <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
        {#if headerActions}
          {@render headerActions()}
        {/if}
        {#if summary}
          <span class="font-sans text-xs text-muted-foreground">{summary}</span>
        {/if}
        {#if !expanded && collapsedSummary}
          <span
            class="max-w-[22rem] truncate font-mono text-xs text-muted-foreground"
            title={collapsedSummary}>{collapsedSummary}</span>
        {/if}
      </div>
    </div>
    <div id={bodyId} class="grid gap-3" hidden={!expanded}>
      {@render children?.()}
    </div>
  </div>
</section>
