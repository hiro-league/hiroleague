import { apiRequest } from './client';

/** One searching use an extension declared (its embed or rerank use) and the profile picked for it. A pick for a use
 *  the extension no longer declares is `removed`. */
export type SearchUse = {
  key: string; // "<extension>:<use id>"
  id: string;
  name: string;
  profile_id: string | null;
  status: 'ok' | 'removed';
};

export type SearchUseGroup = {
  extension: string;
  embedding: SearchUse[];
  rerank: SearchUse[];
};

/** The paired extensions' embedding and reranking uses (Catalog → Profiles → Uses). The profiles and the picks are
 *  written through the preferences API (`embedding.*`, `rerank.*`). */
export const listSearchUses = () => apiRequest<{ extensions: SearchUseGroup[] }>('/search/uses');
