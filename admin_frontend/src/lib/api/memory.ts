import { apiRequest, type ApiResponse } from './client';

export type MemoryListData = {
  memory_enabled: boolean;
  /** Normalized Mem0 rows (shape may evolve with mem0ai). */
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

export async function deleteWorkspaceMemory(memoryId: string): Promise<ApiResponse<MemoryDeleteData>> {
  return apiRequest<MemoryDeleteData>(`/memory/${encodeURIComponent(memoryId)}`, {
    method: 'DELETE'
  });
}
