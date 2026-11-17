import type { GraphEdgeDTO, GraphNodeDTO } from '$kit/memory/source';
import {
	readHidden,
	HIDE_EDGES_KEY,
	HIDE_NODES_KEY,
	writeHidden
} from './graph-persistence';

export function createGraphViewFilters() {
	let hiddenNodeIds = $state<Set<string>>(readHidden(HIDE_NODES_KEY));
	let hiddenEdgeTypes = $state<Set<string>>(readHidden(HIDE_EDGES_KEY));

	function setVisibleNodeIds(type: string, visible: string[], nodes: GraphNodeDTO[]): void {
		const shown = new Set(visible);
		const next = new Set(hiddenNodeIds);
		for (const n of nodes) {
			if (n.type !== type) continue;
			if (shown.has(n.id)) next.delete(n.id);
			else next.add(n.id);
		}
		hiddenNodeIds = next;
		writeHidden(HIDE_NODES_KEY, next);
	}

	function setVisibleEdgeTypes(visible: string[], links: GraphEdgeDTO[]): void {
		const shown = new Set(visible);
		const next = new Set<string>();
		for (const e of links) {
			if (!shown.has(e.rel_type)) next.add(e.rel_type);
		}
		hiddenEdgeTypes = next;
		writeHidden(HIDE_EDGES_KEY, next);
	}

	function clearViewFilters(): void {
		hiddenNodeIds = new Set();
		hiddenEdgeTypes = new Set();
		writeHidden(HIDE_NODES_KEY, hiddenNodeIds);
		writeHidden(HIDE_EDGES_KEY, hiddenEdgeTypes);
	}

	return {
		get hiddenNodeIds() {
			return hiddenNodeIds;
		},
		get hiddenEdgeTypes() {
			return hiddenEdgeTypes;
		},
		setVisibleNodeIds,
		setVisibleEdgeTypes,
		clearViewFilters
	};
}

export type GraphViewFilters = ReturnType<typeof createGraphViewFilters>;
