<script lang="ts">
  import type { EvalEpisode } from '$lib/api/eval';
  import { fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import type { CorpusScrollAnchor } from '$lib/features/eval/state/eval-corpus-scroll-anchor.svelte';

  interface Props {
    filtered: EvalEpisode[];
    episodeNo: Map<string, number>;
    stickyTop: string;
    scrollAnchor: CorpusScrollAnchor;
  }

  let { filtered, episodeNo, stickyTop, scrollAnchor }: Props = $props();

  let railEl = $state<HTMLElement | undefined>(undefined);
  $effect(() => {
    scrollAnchor.setRailEl(railEl);
    return () => scrollAnchor.setRailEl(undefined);
  });
</script>

<nav
  bind:this={railEl}
  aria-label="Episode index"
  class="sticky max-h-[70vh] w-12 shrink-0 overflow-y-auto rounded-md border bg-muted/20 p-1"
  style="top: calc({stickyTop} + 3.25rem);"
>
  {#each filtered as ep (ep.id)}
    <button
      type="button"
      data-rail={ep.id}
      class="block w-full cursor-pointer rounded px-1 py-0.5 text-right font-mono text-[11px] tabular-nums transition-colors hover:bg-primary/10 hover:font-semibold hover:text-primary {scrollAnchor.currentId === ep.id ? 'bg-primary/15 font-semibold text-primary' : 'text-muted-foreground'}"
      title={`${ep.speaker || 'episode'} · ${fmtEpisodeDate(ep.timestamp)}`}
      onclick={() => scrollAnchor.jumpTo(ep.id)}
    >
      {episodeNo.get(ep.id)}
    </button>
  {/each}
</nav>
