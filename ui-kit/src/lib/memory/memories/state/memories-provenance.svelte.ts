// Where one memory fact came from: the conversation turn(s) behind the row's `chunk_ids`, read through the source's
// `chunkDetails` (the same one the graph uses for an episode's text). Summaries carry no `chunk_ids`: an empty
// "no source" state. Its own module so the controller stays about the list.
// UI kit: from the HiroLeague admin's Memories page (features/memories/state/memories-provenance.svelte.ts).
import { errorMessage } from '$kit/api/client';
import type { GraphChunkDetail, MemoryRow, MemorySource } from '$kit/memory/source';
import { memoryChunkIds } from '../shared/memory-pure';

/** `source` is read at each opening, so a host that swaps its source is followed. */
export function createMemoryProvenance(source: () => MemorySource) {
	let row = $state<MemoryRow | null>(null);
	let chunks = $state<GraphChunkDetail[]>([]);
	let loading = $state(false);
	let error = $state('');
	// A newer open() aborts the previous fetch so answers never race.
	let abort: AbortController | null = null;

	async function open(target: MemoryRow) {
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
			const res = await source().chunkDetails(ids, ctrl.signal);
			if (ctrl.signal.aborted) return;
			chunks = res ?? [];
		} catch (e) {
			if (ctrl.signal.aborted) return; // expected when superseded or closed
			error = errorMessage(e);
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
