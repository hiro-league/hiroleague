import type { EvalEpisode } from '$lib/api/eval';
import { corpusScrollAnchorEpisodeId } from '$lib/features/eval/shared/eval-corpus-review-pure';

/** Scroll-spy for the Corpus tab index rail (page-owned scroll, window listeners). */
export function createCorpusScrollAnchor(opts: {
  getEnabled: () => boolean;
  getFiltered: () => EvalEpisode[];
}) {
  const nodes = new Map<string, HTMLElement>();
  let railEl = $state<HTMLElement | undefined>(undefined);
  let currentId = $state<string | null>(null);

  function register(node: HTMLElement, id: string) {
    nodes.set(id, node);
    return {
      destroy() {
        nodes.delete(id);
      }
    };
  }

  function recomputeCurrent() {
    if (!opts.getEnabled()) return;
    const filtered = opts.getFiltered();
    const anchor = (railEl?.getBoundingClientRect().top ?? 0) + 12;
    currentId = corpusScrollAnchorEpisodeId(filtered, nodes, anchor);
  }

  function jumpTo(id: string) {
    currentId = id;
    nodes.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $effect(() => {
    if (!opts.getEnabled()) return;
    opts.getFiltered();
    railEl; // recompute once the index rail mounts (anchor line position)
    recomputeCurrent();
    const onScroll = () => recomputeCurrent();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  });

  $effect(() => {
    if (!opts.getEnabled() || !railEl || !currentId) return;
    const btn = railEl.querySelector(`[data-rail="${CSS.escape(currentId)}"]`);
    btn?.scrollIntoView({ block: 'nearest' });
  });

  return {
    get currentId() {
      return currentId;
    },
    setRailEl(el: HTMLElement | undefined) {
      railEl = el;
    },
    register,
    jumpTo
  };
}

export type CorpusScrollAnchor = ReturnType<typeof createCorpusScrollAnchor>;
