<!--
  L3 — live activity terminal for the Eval Batch.

  A scrollable, monospace, auto-following feed of the run's activity lines
  (built by the pure `eval-activity.ts` helper and passed in as `lines`). The
  collapse/expand affordance is owned by the enclosing collapsible section card
  — this component is just the feed + auto-follow. Virtualized log feed — exempt
  from the shared table primitives per the admin Svelte conventions.
-->
<script lang="ts">
  import type { ActivityLine, ActivityTone } from '$lib/features/eval/shared/eval-activity';

  interface Props {
    lines: ActivityLine[];
  }

  let { lines }: Props = $props();

  const toneClass: Record<ActivityTone, string> = {
    muted: 'text-muted-foreground',
    info: 'text-sky-500 dark:text-sky-400',
    success: 'text-emerald-600 dark:text-emerald-400',
    warn: 'text-amber-600 dark:text-amber-400',
    error: 'text-destructive'
  };

  // Auto-follow: stick to the bottom as lines arrive, but back off the moment the
  // user scrolls up to read history (re-engage when they return to the bottom).
  let scroller = $state<HTMLDivElement | null>(null);
  let pinned = $state(true);

  function onScroll() {
    if (!scroller) return;
    const slack = 24; // px tolerance so "near bottom" still counts as pinned
    pinned = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - slack;
  }

  $effect(() => {
    // Re-run when the line count changes; only follow if the user is pinned.
    void lines.length;
    if (pinned && scroller) scroller.scrollTop = scroller.scrollHeight;
  });
</script>

<div class="grid gap-1">
  <div class="flex items-center gap-2 px-0.5 font-sans text-xs text-muted-foreground">
    <span>{lines.length} {lines.length === 1 ? 'line' : 'lines'}</span>
    {#if !pinned}
      <button
        type="button"
        class="ml-auto rounded border px-2 py-0.5 hover:bg-muted"
        onclick={() => {
          pinned = true;
          if (scroller) scroller.scrollTop = scroller.scrollHeight;
        }}
      >
        Jump to latest
      </button>
    {/if}
  </div>
  <div
    bind:this={scroller}
    onscroll={onScroll}
    class="h-56 overflow-y-auto rounded-md border bg-slate-950 px-3 py-2 font-mono text-xs leading-5 text-slate-200"
    role="log"
    aria-live="polite"
    aria-label="Eval run activity log"
  >
    {#if lines.length === 0}
      <p class="text-slate-500">No activity yet — press “Run eval”.</p>
    {:else}
      {#each lines as line, i (i)}
        <div class="whitespace-pre-wrap break-words {toneClass[line.tone]}">{line.text}</div>
      {/each}
    {/if}
  </div>
</div>
