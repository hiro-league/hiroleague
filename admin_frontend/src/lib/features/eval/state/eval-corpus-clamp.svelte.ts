import { SvelteSet } from 'svelte/reactivity';
import type { EvalEpisode } from '$lib/api/eval';
import { corpusEpisodeNeedsClamp } from '$lib/features/eval/shared/eval-corpus-review-pure';

/** Per-episode expand/collapse for clamped transcript bodies (Corpus tab). */
export function createCorpusClamp(getEpisodes: () => EvalEpisode[]) {
  const expanded = new SvelteSet<string>();

  $effect(() => {
    getEpisodes();
    expanded.clear();
  });

  function toggleExpand(id: string) {
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
  }

  function expandAll(episodes: EvalEpisode[]) {
    for (const ep of episodes) expanded.add(ep.id);
  }

  function collapseAll() {
    expanded.clear();
  }

  function isCollapsed(ep: EvalEpisode, enhanced: boolean, searching: boolean): boolean {
    return enhanced && !searching && corpusEpisodeNeedsClamp(ep) && !expanded.has(ep.id);
  }

  return {
    get expanded() {
      return expanded;
    },
    toggleExpand,
    expandAll,
    collapseAll,
    isCollapsed,
    needsClamp: corpusEpisodeNeedsClamp
  };
}

export type CorpusClamp = ReturnType<typeof createCorpusClamp>;
