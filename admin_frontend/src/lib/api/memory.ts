import { apiRequest, type ApiResponse } from './client';

export type MemoryListData = {
  memory_enabled: boolean;
  /** Normalized memory rows (Graphiti facts-as-memory: memory text + created_at + id + character/source). */
  memories: Record<string, unknown>[];
};

export type MemoryClearData = {
  deleted_count: number;
};

/**
 * List workspace memories. Without `groupId`: all of the default user's conversation-memory
 * groups (the page default). With `groupId`: that one partition's facts — backs the Memories
 * group selector, which can target any graph group (memory / knowledge / eval), like the Graph tab.
 */
export async function listWorkspaceMemories(groupId?: string): Promise<ApiResponse<MemoryListData>> {
  const gid = (groupId ?? '').trim();
  const path = gid ? `/memory/list?group_id=${encodeURIComponent(gid)}` : '/memory/list';
  return apiRequest<MemoryListData>(path);
}

/**
 * Wipe ONE graph partition — backs the "Clear group" action. Unlike the fact-edge delete,
 * this drops the whole group: facts + entities + episodes + communities. The backend
 * re-validates `groupId` against the group grammar.
 */
export async function clearWorkspaceGroup(groupId: string): Promise<ApiResponse<MemoryClearData>> {
  return apiRequest<MemoryClearData>('/memory/clear-group', {
    method: 'POST',
    body: { group_id: groupId }
  });
}

/** Delete several memories (Graphiti fact edges) by id — backs the "Clear memories" action. */
export async function deleteWorkspaceMemories(ids: string[]): Promise<ApiResponse<MemoryClearData>> {
  return apiRequest<MemoryClearData>('/memory/delete', { method: 'POST', body: { ids } });
}
