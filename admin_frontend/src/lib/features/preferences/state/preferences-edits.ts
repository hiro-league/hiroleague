import type { WorkspacePreferences } from '$lib/api/preferences';
import { modalityKeys } from '$lib/features/preferences/shared/preferences-constants';

export function cloneWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return JSON.parse(JSON.stringify(prefs)) as WorkspacePreferences;
}

/** Build the patch payload sent to `patchPreferences` — only changed paths. */
export function editsForSave(
  baseline: WorkspacePreferences,
  draft: WorkspacePreferences
): Record<string, unknown> {
  const edits: Record<string, unknown> = {};
  const add = (path: string, before: unknown, after: unknown) => {
    if (JSON.stringify(before) !== JSON.stringify(after)) edits[path] = after;
  };
  add('llm.default_chat', baseline.llm.default_chat, draft.llm.default_chat || null);
  add('llm.default_stt', baseline.llm.default_stt, draft.llm.default_stt || null);
  add('llm.default_tts', baseline.llm.default_tts, draft.llm.default_tts || null);
  add(
    'llm.default_tuning_profile',
    baseline.llm.default_tuning_profile,
    draft.llm.default_tuning_profile
  );
  add('memory.default_llm', baseline.memory.default_llm, draft.memory.default_llm || null);
  add(
    'memory.default_embedding_model',
    baseline.memory.default_embedding_model,
    draft.memory.default_embedding_model || null
  );
  add(
    'memory.enabled',
    baseline.memory.enabled,
    Boolean(draft.memory.default_llm && draft.memory.default_embedding_model)
  );
  add(
    'memory.default_tuning_profile',
    baseline.memory.default_tuning_profile,
    draft.memory.default_tuning_profile
  );
  for (const key of modalityKeys) {
    add(`media.input.${key}`, baseline.media.input[key], draft.media.input[key]);
    add(`media.output.${key}`, baseline.media.output[key], draft.media.output[key]);
  }
  add('memory.search.enabled', baseline.memory.search.enabled, draft.memory.search.enabled);
  add('memory.extraction.enabled', baseline.memory.extraction.enabled, draft.memory.extraction.enabled);
  add('memory.search.top_k', baseline.memory.search.top_k, draft.memory.search.top_k);
  add('memory.search.threshold', baseline.memory.search.threshold, draft.memory.search.threshold);
  add('memory.search.rerank', baseline.memory.search.rerank, draft.memory.search.rerank);
  add('memory.reranker.enabled', baseline.memory.reranker.enabled, draft.memory.reranker.enabled);
  add('memory.reranker.model', baseline.memory.reranker.model, draft.memory.reranker.model);
  add('memory.reranker.device', baseline.memory.reranker.device, draft.memory.reranker.device);
  add('memory.reranker.batch_size', baseline.memory.reranker.batch_size, draft.memory.reranker.batch_size);
  add(
    'knowledge.default_embedding_model',
    baseline.knowledge.default_embedding_model,
    draft.knowledge.default_embedding_model || null
  );
  add('knowledge.retrieval.top_k', baseline.knowledge.retrieval.top_k, draft.knowledge.retrieval.top_k);
  add('knowledge.retrieval.min_score', baseline.knowledge.retrieval.min_score, draft.knowledge.retrieval.min_score);
  add('knowledge.retrieval.hybrid', baseline.knowledge.retrieval.hybrid, draft.knowledge.retrieval.hybrid);
  add(
    'knowledge.retrieval.sparse_model',
    baseline.knowledge.retrieval.sparse_model,
    draft.knowledge.retrieval.sparse_model
  );
  add(
    'knowledge.retrieval.prefetch_limit',
    baseline.knowledge.retrieval.prefetch_limit,
    draft.knowledge.retrieval.prefetch_limit
  );
  add(
    'knowledge.retrieval.reranker.enabled',
    baseline.knowledge.retrieval.reranker.enabled,
    draft.knowledge.retrieval.reranker.enabled
  );
  add(
    'knowledge.retrieval.reranker.model_id',
    baseline.knowledge.retrieval.reranker.model_id,
    draft.knowledge.retrieval.reranker.model_id || null
  );
  add(
    'knowledge.retrieval.reranker.top_n',
    baseline.knowledge.retrieval.reranker.top_n,
    draft.knowledge.retrieval.reranker.top_n
  );
  add(
    'knowledge.retrieval.reranker.device',
    baseline.knowledge.retrieval.reranker.device,
    draft.knowledge.retrieval.reranker.device
  );
  add(
    'knowledge.retrieval.reranker.batch_size',
    baseline.knowledge.retrieval.reranker.batch_size,
    draft.knowledge.retrieval.reranker.batch_size
  );
  add(
    'knowledge.default_tuning_profile',
    baseline.knowledge.default_tuning_profile,
    draft.knowledge.default_tuning_profile
  );
  add('knowledge.answering.model', baseline.knowledge.answering.model, draft.knowledge.answering.model || null);
  add('knowledge.answering.cite_sources', baseline.knowledge.answering.cite_sources, draft.knowledge.answering.cite_sources);
  add(
    'knowledge.answering.language_policy',
    baseline.knowledge.answering.language_policy,
    draft.knowledge.answering.language_policy
  );
  add('knowledge.chunking.chunk_size', baseline.knowledge.chunking.chunk_size, draft.knowledge.chunking.chunk_size);
  add(
    'knowledge.chunking.chunk_overlap',
    baseline.knowledge.chunking.chunk_overlap,
    draft.knowledge.chunking.chunk_overlap
  );
  add(
    'knowledge.chunking.embed_structural_context',
    baseline.knowledge.chunking.embed_structural_context,
    draft.knowledge.chunking.embed_structural_context
  );
  add(
    'knowledge.chunking.markdown.respect_headings',
    baseline.knowledge.chunking.markdown.respect_headings,
    draft.knowledge.chunking.markdown.respect_headings
  );
  add('knowledge.rewrite.prompt', baseline.knowledge.rewrite.prompt, draft.knowledge.rewrite.prompt);
  add('knowledge.rewrite.default_on', baseline.knowledge.rewrite.default_on, draft.knowledge.rewrite.default_on);
  // Knowledge Graph (Graphiti) prefs were missing here, so backend/model/etc. edits were
  // silently dropped from the save payload (UI showed "saved" but the value snapped back).
  add('knowledge.graph.backend', baseline.knowledge.graph.backend, draft.knowledge.graph.backend);
  add(
    'knowledge.graph.extraction_model',
    baseline.knowledge.graph.extraction_model,
    draft.knowledge.graph.extraction_model || null
  );
  add(
    'knowledge.graph.extraction_tuning_profile',
    baseline.knowledge.graph.extraction_tuning_profile,
    draft.knowledge.graph.extraction_tuning_profile
  );
  add(
    'knowledge.graph.small_model',
    baseline.knowledge.graph.small_model,
    draft.knowledge.graph.small_model || null
  );
  add(
    'knowledge.graph.small_tuning_profile',
    baseline.knowledge.graph.small_tuning_profile,
    draft.knowledge.graph.small_tuning_profile
  );
  add(
    'knowledge.graph.embedder_model',
    baseline.knowledge.graph.embedder_model,
    draft.knowledge.graph.embedder_model || null
  );
  add(
    'knowledge.graph.temporal_default',
    baseline.knowledge.graph.temporal_default,
    draft.knowledge.graph.temporal_default
  );
  add('knowledge.graph.k_hop', baseline.knowledge.graph.k_hop, draft.knowledge.graph.k_hop);
  add(
    'knowledge.graph.search_recipe',
    baseline.knowledge.graph.search_recipe,
    draft.knowledge.graph.search_recipe
  );
  add(
    'knowledge.graph.ledger_detail',
    baseline.knowledge.graph.ledger_detail,
    draft.knowledge.graph.ledger_detail
  );
  add(
    'knowledge.graph.reranker.model_id',
    baseline.knowledge.graph.reranker.model_id,
    draft.knowledge.graph.reranker.model_id || null
  );
  add(
    'knowledge.graph.reranker.min_relevance',
    baseline.knowledge.graph.reranker.min_relevance,
    draft.knowledge.graph.reranker.min_relevance
  );
  add(
    'knowledge.graph.reranker.device',
    baseline.knowledge.graph.reranker.device,
    draft.knowledge.graph.reranker.device || null
  );
  add('chat.instructions', baseline.chat.instructions, draft.chat.instructions);
  add('chat.max_messages', baseline.chat.max_messages, draft.chat.max_messages);
  add('chat.cite_sources', baseline.chat.cite_sources, draft.chat.cite_sources);
  add('tuning_profiles', baseline.tuning_profiles, draft.tuning_profiles);
  return edits;
}
