<script lang="ts">
	// The gallery's memory pieces: the memories table and the entity graph (kit memory/), fed by a made-up
	// `MemorySource` so they run with no backend. Deleting or clearing here only changes this page's copy.
	import Segmented from '$kit/ui/segmented.svelte';
	import GraphPanel from '$kit/memory/graph/graph-panel.svelte';
	import { createGraphModel } from '$kit/memory/graph/state/create-graph-model.svelte';
	import MemoriesPanel from '$kit/memory/memories/memories-panel.svelte';
	import type { GraphEdgeDTO, GraphNodeDTO, MemoryRow, MemorySource } from '$kit/memory/source';

	const GROUP = 'mem_1_hiro';
	const node = (id: string, name: string, type: string, summary: string): GraphNodeDTO => ({
		id,
		name,
		type,
		aliases: [],
		chunk_ids: ['c1'],
		document_ids: [],
		summary
	});
	const edge = (id: string, source: string, target: string, rel_type: string, fact: string, valid_at: string): GraphEdgeDTO => ({
		id,
		source,
		target,
		rel_type,
		fact,
		chunk_ids: ['c1'],
		document_ids: [],
		valid_at,
		invalid_at: null,
		expired_at: null,
		created_at: valid_at
	});
	const NODES = [
		node('n1', 'Sam', 'Person', 'Sam lives in the house and plays the piano.'),
		node('n2', 'Piano', 'Object', 'An upright piano in the living room.'),
		node('n3', 'Living room', 'Place', 'The room with the piano and the big window.'),
		node('n4', 'Lina', 'Person', 'Lina is Sam’s sister; she studies on Tuesdays.')
	];
	const EDGES = [
		edge('e1', 'n1', 'n2', 'PLAYS', 'Sam plays the piano every evening.', '2026-10-02T18:00:00Z'),
		edge('e2', 'n2', 'n3', 'LOCATED_IN', 'The piano is in the living room.', '2026-09-14T09:00:00Z'),
		edge('e3', 'n1', 'n4', 'SIBLING_OF', 'Sam and Lina are siblings.', '2026-08-01T12:00:00Z')
	];
	let memories = $state<MemoryRow[]>(
		EDGES.map((e) => ({ id: e.id, memory: e.fact, kind: 'relation', group_id: GROUP, agent_id: 'hiro', created_at: e.created_at, chunk_ids: e.chunk_ids }))
	);

	const source: MemorySource = {
		exportGraph: async () => ({ nodes: NODES, edges: EDGES, truncated: false, counts: { nodes: NODES.length, edges: EDGES.length } }),
		listGroups: async () => ({ default_group_id: GROUP, groups: [{ id: GROUP, label: 'Hiro’s memory', kind: 'memory' }] }),
		listEpisodes: async () => [
			{ id: 'c1', snippet: 'Sam: I play every evening.', preview: 'Sam: I play every evening.', valid_at: '2026-10-02T18:00:00Z', document_id: 'conv:1' }
		],
		chunkDetails: async (ids) =>
			ids.map((id) => ({ id, text: 'Sam: I play the piano every evening, in the living room.', document_id: 'conv:1', document_title: 'Conversation', ord: null, heading_path: null, valid_at: '2026-10-02T18:00:00Z' })),
		listMemories: async () => ({ memory_enabled: true, memories }),
		deleteMemories: async (ids) => {
			memories = memories.filter((m) => !ids.includes(String(m.id)));
			return ids.length;
		},
		clearGroup: async () => {
			const n = memories.length;
			memories = [];
			return n;
		},
		characters: async () => [{ id: 'hiro', name: 'Hiro' }]
	};

	let view = $state<'memories' | 'graph'>('memories');
	let graphError = $state<string | null>(null);
	const graph = createGraphModel({ source, setError: (msg) => (graphError = msg) });
</script>

<div class="flex flex-col gap-3">
	<Segmented
		label="Memory piece"
		value={view}
		options={[
			{ value: 'memories', label: 'Memories table' },
			{ value: 'graph', label: 'Graph' }
		]}
		onchange={(v) => (view = v as 'memories' | 'graph')}
	/>
	{#if graphError}<p class="text-sm text-destructive">{graphError}</p>{/if}
	<MemoriesPanel {source} hidden={view !== 'memories'} />
	{#if view === 'graph'}
		<GraphPanel {graph} emptyMessage="No sample graph." />
	{/if}
</div>
