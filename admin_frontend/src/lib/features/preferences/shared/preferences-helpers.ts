import type { WorkspacePreferences } from '$lib/api/preferences';

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
