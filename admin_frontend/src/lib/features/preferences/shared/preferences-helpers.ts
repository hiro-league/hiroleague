import type { WorkspacePreferences } from '$lib/api/preferences';
import type { LocalRerankerRow } from '$lib/api/knowledge';

// Phase 7b step 5: `model_resolved_source` is the AI-profile field supplying the answering model
// (its own profile, else Hiro's chat profile); it was the model field's path.
const knowledgeModelSourceLabels: Record<string, string> = {
  'knowledge.answering.profile': 'the knowledge answering profile',
  'llm.chat_profile': "Hiro's chat profile"
};

export function knowledgeAnsweringModelHint(prefs: WorkspacePreferences): string {
  const resolved = prefs.knowledge.answering.model_resolved;
  const source = prefs.knowledge.answering.model_resolved_source;
  const resolvedLabel = resolved ?? 'none (no profile set, or its model is unavailable)';
  if (!prefs.knowledge.answering.profile && source) {
    const sourceLabel = knowledgeModelSourceLabels[source] ?? source;
    return `Not set: uses ${sourceLabel}. Effective model (saved): ${resolvedLabel}.`;
  }
  return `Effective model (saved): ${resolvedLabel}.`;
}

/** Prefetch limit applies only when hybrid retrieval runs separate dense + BM25 branches. */
export function knowledgeHybridPrefetchActive(
  prefs: WorkspacePreferences | null | undefined
): boolean {
  return Boolean(prefs?.knowledge.retrieval.hybrid);
}

/** Top N after rerank applies only when reranking is enabled with a usable model. */
export function knowledgeRerankTopNActive(
  prefs: WorkspacePreferences | null | undefined,
  localRerankers: LocalRerankerRow[],
  activeProvidersResolved: boolean,
  rerankActiveProviderIds: Set<string>
): boolean {
  const reranker = prefs?.knowledge.retrieval.reranker;
  if (!reranker?.enabled || !reranker.model_id?.trim()) return false;

  const modelId = reranker.model_id.trim();
  const local = localRerankers.find((row) => row.id === modelId);
  if (local) {
    return Boolean(local.downloaded || local.status === 'ready');
  }

  const colon = modelId.indexOf(':');
  if (colon <= 0) return false;
  const providerId = modelId.slice(0, colon);
  // Match SingleModelPicker: until active providers resolve, don't treat cloud models as unavailable.
  if (!activeProvidersResolved) return true;
  return rerankActiveProviderIds.has(providerId);
}
