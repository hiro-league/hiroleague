import { apiRequest, type ApiResponse } from './client';

export type MemoryListData = {
  memory_enabled: boolean;
  /** Normalized memory rows (Graphiti facts-as-memory: memory text + created_at + id + character/source). */
  memories: Record<string, unknown>[];
};

export type MemoryClearData = {
  deleted_count: number;
};

export type MemoryDeleteData = {
  memory_id: string;
};

export async function listWorkspaceMemories(): Promise<ApiResponse<MemoryListData>> {
  return apiRequest<MemoryListData>('/memory/list');
}

export async function clearWorkspaceMemories(): Promise<ApiResponse<MemoryClearData>> {
  return apiRequest<MemoryClearData>('/memory/clear', { method: 'POST' });
}

/** Delete several memories (Graphiti fact edges) by id — backs the "Clear shown" action. */
export async function deleteWorkspaceMemories(ids: string[]): Promise<ApiResponse<MemoryClearData>> {
  return apiRequest<MemoryClearData>('/memory/delete', { method: 'POST', body: { ids } });
}

export async function deleteWorkspaceMemory(memoryId: string): Promise<ApiResponse<MemoryDeleteData>> {
  return apiRequest<MemoryDeleteData>(`/memory/${encodeURIComponent(memoryId)}`, {
    method: 'DELETE'
  });
}
