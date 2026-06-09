import {
  clearWorkspaceMemories,
  deleteWorkspaceMemories,
  listWorkspaceMemories
} from '$lib/api/memory';

/** List workspace long-term memories (Graphiti); mirrors prior controller try/catch (api throws on HTTP / payload errors).
 *  `groupId` (optional) scopes the list to one graph partition — backs the Memories group selector. */
export async function graphRunsLoadMemoriesList(groupId?: string): Promise<{
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

export async function graphRunsClearAllMemories(): Promise<void> {
  await clearWorkspaceMemories();
}

/** Delete several memories at once (the filtered "Clear shown" set). No-op on empty input. */
export async function graphRunsDeleteMemories(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  await deleteWorkspaceMemories(ids);
}
