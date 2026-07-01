import {
  clearWorkspaceGroup,
  deleteWorkspaceMemories,
  listWorkspaceMemories
} from '$lib/api/memory';

/** List workspace long-term memories (Graphiti); api throws on HTTP / payload errors.
 *  `groupId` (optional) scopes the list to one graph partition — backs the group selector. */
export async function loadMemoriesList(groupId?: string): Promise<{
  memoryEnabled: boolean | null;
  memories: Record<string, unknown>[];
  error: string;
}> {
  try {
    const res = await listWorkspaceMemories(groupId);
    return {
      memoryEnabled: res.data.memory_enabled,
      memories: res.data.memories ?? [],
      error: ''
    };
  } catch (e) {
    return {
      memoryEnabled: null,
      memories: [],
      error: e instanceof Error ? e.message : 'Failed to load memories.'
    };
  }
}

/** Wipe one whole partition (facts + entities + episodes + communities) — "Clear group". */
export async function clearGroup(groupId: string): Promise<void> {
  const gid = groupId.trim();
  if (!gid) return;
  await clearWorkspaceGroup(gid);
}

/** Delete several memories at once (the filtered "Clear memories" set). No-op on empty input. */
export async function deleteMemories(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  await deleteWorkspaceMemories(ids);
}
