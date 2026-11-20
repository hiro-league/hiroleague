<script lang="ts">
  // A story's timed steps as a waterfall: each step a bar from when it started to when it ended, under its parent,
  // in its part's place. New (no kit piece or shadcn-svelte component draws one; closest: the kit's area chart, which
  // plots values over time, not spans).
  import { cn } from '$lib/utils';
  import PartIcon from './PartIcon.svelte';
  import { isCore, partLabel } from './parts';
  import { duration } from './story-format';
  import type { StoryStep } from './kinds';

  let { steps, total }: { steps: StoryStep[]; total: number } = $props();
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / Math.max(total, 1)) * 100))}%`;
</script>

<div class="space-y-1">
  {#each steps as s, i (i)}
    <div class="grid grid-cols-[minmax(10rem,16rem)_1fr_4.5rem] items-center gap-3 text-[0.82rem]">
      <div class="flex min-w-0 items-center gap-1.5" style:padding-left={`${s.depth * 0.9}rem`}>
        <PartIcon source={s.source} size={12} class="shrink-0 text-muted-foreground" />
        <span class="truncate font-mono text-xs" title={`${s.step} · ${partLabel(s.source)}`}>{s.step}</span>
      </div>
      <div class="relative h-4 rounded-sm bg-muted/50">
        <div
          class={cn(
            'absolute top-0.5 bottom-0.5 min-w-[3px] rounded-sm',
            s.outcome === 'error' ? 'bg-destructive/70' : isCore(s.source) ? 'bg-primary/60' : 'bg-chart-2/70'
          )}
          style:left={pct(s.start_ms)}
          style:width={pct(s.elapsed_ms)}
          title={`${s.step}: ${duration(s.elapsed_ms)}, ${s.outcome}, from +${duration(s.start_ms)}`}
        ></div>
      </div>
      <span class={cn('text-right tabular-nums text-xs', s.outcome === 'error' ? 'text-destructive' : 'text-muted-foreground')}>
        {duration(s.elapsed_ms)}
      </span>
    </div>
  {/each}
  <div class="flex flex-wrap gap-x-4 pt-1 text-[11px] text-muted-foreground">
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-sm bg-primary/60"></span>the core</span>
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-sm bg-chart-2/70"></span>an app or the phone</span>
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-sm bg-destructive/70"></span>failed</span>
  </div>
</div>
