import type { MemorySource, NamedItem } from '$kit/memory/source';
import { listCharacters } from '$lib/api/characters';
import { listChatChannels } from '$lib/api/chat-channels';
import {
  exportKnowledgeGraph,
  fetchGraphChunksDetail,
  listKnowledgeGraphEpisodes,
  listKnowledgeGraphGroups,
  searchGraphChunks
} from '$lib/api/knowledge';
import { clearWorkspaceGroup, deleteWorkspaceMemories, listWorkspaceMemories } from '$lib/api/memory';
import { getPreferences } from '$lib/api/preferences';
import { connectKnowledgeGraphEvents } from '$lib/features/knowledge/shared/knowledge-events';

/**
 * The admin's data for the kit's graph viewer and memories table: its own API calls (which send the selected
 * workspace), the characters and chat channels that name a memory's rows, the shared `/api/knowledge/events`
 * stream for live graph updates, and the graph's large-type threshold from preferences.
 */
export const adminMemorySource: MemorySource = {
  exportGraph: (opts) => exportKnowledgeGraph(opts),
  listGroups: () => listKnowledgeGraphGroups(),
  listEpisodes: async (groupId) => (await listKnowledgeGraphEpisodes(groupId)).episodes,
  chunkDetails: async (chunkIds, signal) => (await fetchGraphChunksDetail(chunkIds, signal)).chunks,
  searchChunks: async (text, signal) => (await searchGraphChunks(text, signal)).point_ids,
  listMemories: (groupId) => listWorkspaceMemories(groupId),
  deleteMemories: async (ids) => (await deleteWorkspaceMemories(ids)).deleted_count,
  clearGroup: async (groupId) => (await clearWorkspaceGroup(groupId)).deleted_count,
  characters: async (): Promise<NamedItem[]> =>
    (await listCharacters()).map((c) => ({ id: c.id, name: c.name, photo: c.photo_data_url ?? null })),
  channels: async (): Promise<NamedItem[]> =>
    (await listChatChannels()).map((ch) => ({
      id: String(ch.id),
      name: ch.name,
      photo: ch.photo_data_url ?? null,
      characterName: ch.character?.name ?? null
    })),
  live: (handlers) => connectKnowledgeGraphEvents(handlers),
  largeTypeThreshold: async () => {
    const t = (await getPreferences())?.preferences?.graph?.view?.large_type_threshold;
    return typeof t === 'number' ? t : null;
  }
};
