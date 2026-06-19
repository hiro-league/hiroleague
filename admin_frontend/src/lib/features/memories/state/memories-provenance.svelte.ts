/**
 * Provenance drill-down for a single memory fact: resolves the originating conversation
 * turn(s) from the row's `chunk_ids` via the shared chunk-detail endpoint (the same one the
 * Graph tab uses to read episode text from Kuzu). Summaries carry no `chunk_ids` → an empty
 * "no source" state. Self-contained so the page controller stays focused on the list.
 */
import { fetchGraphChunksDetail, type GraphChunkDetail } from '$lib/api/knowledge';
import { memoryChunkIds } from '../shared/memory-pure';

export function createMemoryProvenance() {
  let row = $state<Record<string, unknown> | null>(null);
  let chunks = $state<GraphChunkDetail[]>([]);
  let loading = $state(false);
  let error = $state('');
  // A superseding open() aborts the previous in-flight fetch so chunks never race.
  let abort: AbortController | null = null;

  async function open(target: Record<string, unknown>) {
    abort?.abort();
    row = target;
    chunks = [];
    error = '';
    const ids = memoryChunkIds(target);
    if (ids.length === 0) {
      loading = false;
      return; // summaries (and any unciteable fact) carry no chunk provenance
    }
    loading = true;
    const ctrl = new AbortController();
    abort = ctrl;
    try {
      const res = await fetchGraphChunksDetail(ids, ctrl.signal);
      if (ctrl.signal.aborted) return;
      chunks = res.data?.chunks ?? [];
    } catch (e) {
      if (ctrl.signal.aborted) return; // expected when superseded / closed
      error = e instanceof Error ? e.message : 'Failed to load source turns.';
    } finally {
      if (!ctrl.signal.aborted) loading = false;
    }
  }

  function close() {
    abort?.abort();
    abort = null;
    row = null;
    chunks = [];
    error = '';
    loading = false;
  }

  return {
    get row() {
      return row;
    },
    get chunks() {
      return chunks;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    open,
    close
  };
}

export type MemoryProvenance = ReturnType<typeof createMemoryProvenance>;
