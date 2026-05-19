import { clearWorkspaceMemories, deleteWorkspaceMemory, listWorkspaceMemories } from '$lib/api/memory';

/** List Mem0 workspace memories; mirrors prior controller try/catch (api throws on HTTP / payload errors). */
export async function graphRunsLoadMemoriesList(): Promise<{
  memoryEnabled: boolean | null;
  memories: Record<string, unknown>[];
  error: string;
}> {
  try {
    const res = await listWorkspaceMemories();
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

export async function graphRunsDeleteMemory(memoryId: string): Promise<void> {
  await deleteWorkspaceMemory(memoryId);
}
