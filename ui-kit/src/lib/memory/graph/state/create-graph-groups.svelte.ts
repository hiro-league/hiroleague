import type { GraphGroup, MemorySource } from '$kit/memory/source';
import { readActiveGroup, writeActiveGroup } from './graph-persistence';

export function createGraphGroups(deps: {
	source: MemorySource;
	onGroupChanged: (id: string | null) => Promise<void>;
}) {
	let groups = $state<GraphGroup[]>([]);
	let activeGroupId = $state<string | null>(null);

	async function loadGroups(): Promise<void> {
		// A failed read leaves the groups as they were.
		const res = await deps.source.listGroups().catch(() => null);
		if (!res) return;
		groups = res.groups;
		const ids = new Set(groups.map((g) => g.id));
		if (activeGroupId && ids.has(activeGroupId)) return;
		const remembered = readActiveGroup();
		activeGroupId = remembered && ids.has(remembered) ? remembered : (groups[0]?.id ?? null);
	}

	async function selectGroup(id: string | null): Promise<void> {
		if (id === activeGroupId) return;
		activeGroupId = id;
		writeActiveGroup(id);
		await deps.onGroupChanged(id);
	}

	function eventMatchesActiveGroup(gid: string | null | undefined): boolean {
		if (activeGroupId === null) return false;
		return (gid ?? '') === activeGroupId;
	}

	return {
		get groups() {
			return groups;
		},
		get activeGroupId() {
			return activeGroupId;
		},
		loadGroups,
		selectGroup,
		eventMatchesActiveGroup
	};
}

export type GraphGroups = ReturnType<typeof createGraphGroups>;
