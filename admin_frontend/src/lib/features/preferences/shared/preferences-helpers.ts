import type { WorkspacePreferences } from '$lib/api/preferences';
import type { LocalRerankerRow } from '$lib/api/knowledge';

const knowledgeModelSourceLabels: Record<string, string> = {
  'knowledge.answering.model': 'knowledge answering model preference',
  'llm.default_chat': 'workspace default chat model'
};

export function knowledgeAnsweringModelHint(prefs: WorkspacePreferences): string {
  const resolved = prefs.knowledge.answering.model_resolved;
  const source = prefs.knowledge.answering.model_resolved_source;
  const resolvedLabel = resolved ?? 'none (model unavailable or not configured)';
  if (!prefs.knowledge.answering.model) {
    const sourceLabel = source ? (knowledgeModelSourceLabels[source] ?? source) : 'default';
    return `Null inherits ${sourceLabel}. Effective model: ${resolvedLabel}.`;
  }
  return `Effective model: ${resolvedLabel}.`;
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
