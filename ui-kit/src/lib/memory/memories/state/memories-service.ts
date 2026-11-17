// The memories table's calls, through the app's `MemorySource`.
// UI kit: from the HiroLeague admin's Memories page (features/memories/state/memories-service.ts).
import { errorMessage } from '$kit/api/client';
import type { MemoryRow, MemorySource } from '$kit/memory/source';

/** The long-term memories (Graphiti) of one partition (`groupId`), or the default user's without one. A failure
 *  answers its message instead of throwing. */
export async function loadMemoriesList(
	source: MemorySource,
	groupId?: string
): Promise<{ memoryEnabled: boolean | null; memories: MemoryRow[]; error: string }> {
	try {
		const res = await source.listMemories(groupId);
		return { memoryEnabled: res.memory_enabled, memories: res.memories ?? [], error: '' };
	} catch (e) {
		return { memoryEnabled: null, memories: [], error: errorMessage(e) };
	}
}

/** Wipes one whole partition (facts, entities, episodes, communities): "Clear group". */
export async function clearGroup(source: MemorySource, groupId: string): Promise<void> {
	const gid = groupId.trim();
	if (!gid) return;
	await source.clearGroup(gid);
}

/** Deletes several memories at once (the filtered "Clear memories" set). Nothing on an empty list. */
export async function deleteMemories(source: MemorySource, ids: string[]): Promise<void> {
	if (ids.length === 0) return;
	await source.deleteMemories(ids);
}
